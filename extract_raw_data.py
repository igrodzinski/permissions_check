import looker_sdk
import api
import json
import logging
import argparse
from typing import Any
from looker_sdk.sdk.api40.models import WriteQuery

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def serialize_looker_obj(obj: Any) -> Any:
    """Helper to convert Looker SDK objects to serializable dicts."""
    if hasattr(obj, '__dict__'):
        # Filter out internal properties and None values to keep JSON clean
        return {k: serialize_looker_obj(v) for k, v in obj.__dict__.items() if not k.startswith('_') and v is not None}
    elif isinstance(obj, list):
        return [serialize_looker_obj(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: serialize_looker_obj(v) for k, v in obj.items()}
    else:
        return obj

def process_permissions(raw_data: dict) -> dict:
    """Prekalkuluje logikę dostępową i wstrzyknie słownik permissions do ról, grup i userów."""
    roles_dict = {str(r.get("id")): r for r in raw_data.get("roles", []) if isinstance(r, dict)}
    model_sets_dict = {str(ms.get("id")): ms for ms in raw_data.get("model_sets", []) if isinstance(ms, dict)}
    
    # 1. Mapowania pomocnicze
    role_to_models = {}
    for role_id, role in roles_dict.items():
        ms_id = str(role.get("model_set_id"))
        ms = model_sets_dict.get(ms_id, {})
        role_to_models[role_id] = ms.get("models", [])
        
    model_to_explores = {}
    for model_name, explores in raw_data.get("explores", {}).items():
        model_to_explores[model_name] = [e.get("name") for e in explores if isinstance(e, dict)]
        
    explore_to_dashboards = {}
    for sa in raw_data.get("system_activity_dashboards", []):
        if not isinstance(sa, dict): continue
        m = sa.get("query.model")
        e = sa.get("query.view")
        d_id = str(sa.get("dashboard.id"))
        d_folder = str(sa.get("dashboard.folder_id"))
        key = f"{m}::{e}"
        if key not in explore_to_dashboards:
            explore_to_dashboards[key] = []
        explore_to_dashboards[key].append({"id": d_id, "folder_id": d_folder})
        
    group_to_folders = {}
    for folder_id, accesses in raw_data.get("folder_accesses", {}).items():
        for acc in accesses:
            g_id = str(acc.get("group_id"))
            if g_id not in group_to_folders:
                group_to_folders[g_id] = set()
            group_to_folders[g_id].add(str(folder_id))
            
    group_to_roles = {}
    for role_id, r_groups in raw_data.get("role_groups", {}).items():
        for g in r_groups:
            g_id = str(g.get("group_id"))
            if g_id not in group_to_roles:
                group_to_roles[g_id] = set()
            group_to_roles[g_id].add(role_id)
            
    user_to_groups = {}
    for g_id, users in raw_data.get("group_users", {}).items():
        for u_id in users:
            u_id = str(u_id)
            if u_id not in user_to_groups:
                user_to_groups[u_id] = set()
            user_to_groups[u_id].add(g_id)

    # 2. Rola -> permissions
    for role in raw_data.get("roles", []):
        if not isinstance(role, dict): continue
        r_id = str(role.get("id"))
        perms = {"models": set(), "explores": set(), "dashboards": set()}
        models = role_to_models.get(r_id, [])
        perms["models"].update(models)
        for m in models:
            explores = model_to_explores.get(m, [])
            for e in explores:
                perms["explores"].add(f"{m}::{e}")
                dashboards = explore_to_dashboards.get(f"{m}::{e}", [])
                for d in dashboards:
                    perms["dashboards"].add(d["id"])
        role["permissions"] = {k: list(v) for k, v in perms.items()}

    # 3. Grupa -> permissions
    for group in raw_data.get("groups", []):
        if not isinstance(group, dict): continue
        g_id = str(group.get("id"))
        g_name = group.get("name", "")
        # Pomijanie grup zaczynających się od 4 (zgodnie z prośbą)
        if str(g_name).startswith("4"):
            continue
            
        perms = {"models": set(), "explores": set(), "dashboards": set()}
        r_ids = group_to_roles.get(g_id, set())
        for r_id in r_ids:
            models = role_to_models.get(r_id, [])
            perms["models"].update(models)
            for m in models:
                explores = model_to_explores.get(m, [])
                for e in explores:
                    perms["explores"].add(f"{m}::{e}")
                    
        # Dashboardy ze zgodnością folderów
        allowed_folders = group_to_folders.get(g_id, set())
        for explore_key in perms["explores"]:
            dashboards = explore_to_dashboards.get(explore_key, [])
            for d in dashboards:
                if d["folder_id"] in allowed_folders:
                    perms["dashboards"].add(d["id"])
                    
        group["permissions"] = {k: list(v) for k, v in perms.items()}

    # 4. User -> permissions
    for user in raw_data.get("users", []):
        if not isinstance(user, dict): continue
        u_id = str(user.get("id"))
        perms = {"models": set(), "explores": set(), "dashboards": set()}
        
        u_roles = set([str(r) for r in user.get("role_ids", [])])
        u_groups = user_to_groups.get(u_id, set())
        
        for g_id in u_groups:
            u_roles.update(group_to_roles.get(g_id, set()))
            
        for r_id in u_roles:
            models = role_to_models.get(r_id, [])
            perms["models"].update(models)
            for m in models:
                explores = model_to_explores.get(m, [])
                for e in explores:
                    perms["explores"].add(f"{m}::{e}")
                    
        u_folders = set()
        for g_id in u_groups:
            u_folders.update(group_to_folders.get(g_id, set()))
            
        for explore_key in perms["explores"]:
            dashboards = explore_to_dashboards.get(explore_key, [])
            for d in dashboards:
                if d["folder_id"] in u_folders:
                    perms["dashboards"].add(d["id"])
                    
        user["permissions"] = {k: list(v) for k, v in perms.items()}

    return raw_data

def extract_raw_data(target_model_name: str):
    logger.info("Inicjalizacja przez zewnętrzny plik api...")
    
    raw_data = {
        "metadata": {
            "target_model": target_model_name
        },
        "users": [],
        "roles": [],
        "role_groups": {},
        "model_sets": [],
        "groups": [],
        "models": [],
        "explores": {},
        "dashboards": [],
        "system_activity_dashboards": [],
        "folders": [],
        "folder_accesses": {},
        "group_users": {},
        "user_attributes": [],
        "user_attribute_group_values": {},
        "user_attribute_user_values": {}
    }

    # 1. Models and Explores
    logger.info("Pobieranie modeli (Models)...")
    models = api.sdk.all_lookml_models(fields="name,explores")
    
    if target_model_name != "all":
        target_models = [m for m in models if m.name == target_model_name]
        if not target_models:
            logger.error(f"Model '{target_model_name}' nie został znaleziony.")
            return
    else:
        target_models = models
        
    raw_data["models"] = serialize_looker_obj(target_models)
    
    logger.info("Pobieranie eksploracji (Explores)...")
    for model in target_models:
        model_explores = []
        for explore in model.explores or []:
            try:
                explore_details = api.sdk.lookml_model_explore(
                    lookml_model_name=model.name,
                    explore_name=explore.name,
                    fields="name,model_name,required_access_grants"
                )
                model_explores.append(serialize_looker_obj(explore_details))
            except Exception as e:
                logger.warning(f"Nie udało się pobrać szczegółów explore {explore.name} (Model: {model.name}): {e}")
        raw_data["explores"][model.name] = model_explores

    # 2. System Activity Dashboards
    logger.info("Pobieranie powiązań Dashboardów z System Activity...")
    try:
        filters = {}
        if target_model_name != "all":
            filters["query.model"] = target_model_name

        sa_query = WriteQuery(
            model="system__activity",
            view="dashboard",
            fields=["dashboard.id", "dashboard.title", "dashboard.folder_id", "query.model", "query.view"],
            filters=filters
        )
        response_json = api.sdk.run_inline_query(result_format="json", body=sa_query)
        raw_data["system_activity_dashboards"] = json.loads(response_json)
    except Exception as e:
        logger.warning(f"Błąd podczas pobierania System Activity: {e}")

    # 3. Dashboards
    logger.info("Pobieranie Dashboardów...")
    dashboards = api.sdk.all_dashboards(fields="id,title,folder_id")
    # Zoptymalizuj zapis - zrzucamy tylko te, które się pojawiły w modelu (lub wszystkie)
    if target_model_name != "all":
        sa_dash_ids = {str(d.get("dashboard.id")) for d in raw_data["system_activity_dashboards"]}
        filtered_dashboards = [d for d in dashboards if str(d.id) in sa_dash_ids]
        raw_data["dashboards"] = serialize_looker_obj(filtered_dashboards)
    else:
        raw_data["dashboards"] = serialize_looker_obj(dashboards)

    # 4. Users, Groups, Roles and Model Sets
    logger.info("Pobieranie Użytkowników, Grup, Ról i Model Sets...")
    raw_data["users"] = serialize_looker_obj(api.sdk.all_users(fields="id,email,display_name,group_ids,role_ids"))
    
    roles = api.sdk.all_roles()
    raw_data["roles"] = serialize_looker_obj(roles)
    
    logger.info("Pobieranie relacji Role -> Group...")
    for role in roles:
        try:
            r_groups = api.sdk.role_groups(role_id=role.id)
            raw_data["role_groups"][str(role.id)] = serialize_looker_obj(r_groups)
        except Exception as e:
            pass
            
    raw_data["model_sets"] = serialize_looker_obj(api.sdk.all_model_sets())
    
    groups_response = api.sdk.all_groups(fields="id,name")
    raw_data["groups"] = serialize_looker_obj(groups_response)
    
    logger.info("Mapowanie przypisań użytkowników do grup...")
    raw_data["group_users"] = {}
    for g in groups_response:
        try:
            g_users = api.sdk.all_group_users(group_id=g.id)
            if g_users:
                raw_data["group_users"][str(g.id)] = [str(getattr(u, 'id', u.get('id') if isinstance(u, dict) else None)) for u in g_users]
        except Exception as e:
            logger.warning(f"Błąd all_group_users dla grupy {g.id}: {e}")

    # 5. Access Grants Mapping (User Attributes)
    logger.info("Pobieranie Atrybutów Użytkownika dla Access Grants...")
    try:
        user_attributes = api.sdk.all_user_attributes()
        # Filtrujemy już w Pythonie obiekty z is_system == False i zapisujemy tylko potrzebne pola
        filtered_ua = [{"id": ua.id, "name": ua.name} for ua in user_attributes if not getattr(ua, 'is_system', False)]
        raw_data["user_attributes"] = filtered_ua
        
        logger.info("Pobieranie wartości User Attributes dla Grup...")
        for ua_dict in filtered_ua:
            try:
                ua_group_vals = api.sdk.all_user_attribute_group_values(user_attribute_id=ua_dict["id"])
                raw_data["user_attribute_group_values"][str(ua_dict["id"])] = serialize_looker_obj(ua_group_vals)
            except Exception as e:
                pass
                
        logger.info("Pobieranie wartości User Attributes bezpośrednio dla Użytkowników...")
        for u in raw_data["users"]:
            u_id = u.get("id")
            if u_id:
                try:
                    u_vals = api.sdk.user_attribute_user_values(user_id=u_id)
                    raw_data["user_attribute_user_values"][str(u_id)] = serialize_looker_obj(u_vals)
                except Exception as e:
                    pass
    except Exception as e:
        logger.warning(f"Błąd podczas pobierania User Attributes: {e}")

    # 6. Folders and Folder Accesses
    logger.info("Pobieranie Folderów i ich Uprawnień...")
    folders = api.sdk.all_folders(fields="id,name,content_metadata_id")
    raw_data["folders"] = serialize_looker_obj(folders)
    
    for folder in folders:
        # Pomiń foldery bez metadata_id
        if folder.content_metadata_id:
            try:
                accesses = api.sdk.all_content_metadata_accesses(content_metadata_id=folder.content_metadata_id)
                if accesses:
                    raw_data["folder_accesses"][folder.id] = serialize_looker_obj(accesses)
            except Exception as e:
                pass

    # Aplikowanie pre-kalkulacji uprawnień
    logger.info("Przetwarzanie i aplikowanie mapy uprawnień...")
    raw_data = process_permissions(raw_data)

    # Zapis do pliku
    output_filename = "raw_looker_data.json"
    logger.info(f"Zapisywanie danych do pliku: {output_filename} ...")
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=2)
    logger.info("Pomyślnie zapisano surowe dane (wraz z permissions)!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Looker Raw Data Extractor")
    parser.add_argument("--model", default="all", help="Nazwa konkretnego modelu do ograniczenia ekstrakcji (domyślnie 'all' czyli pobiera całą instancję).")
    args = parser.parse_args()

    extract_raw_data(args.model)
