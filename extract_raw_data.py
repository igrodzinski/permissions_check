import looker_sdk
import json
import logging
import argparse
from typing import Any

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

def extract_raw_data(target_model_name: str):
    # INSTRUCTION FROM USER:
    path_api = "" # Uzupełnione ręcznie
    logger.info("Inicjalizacja Looker SDK...")
    sdk = looker_sdk.init40(path_api)
    
    raw_data = {
        "metadata": {
            "target_model": target_model_name
        },
        "users": [],
        "roles": [],
        "groups": [],
        "role_groups": {},
        "models": [],
        "explores": {},
        "dashboards": [],
        "system_activity_dashboards": [],
        "model_sets": [],
        "permission_sets": [],
        "folders": [],
        "folder_accesses": {},
        "user_attributes": [],
        "user_attribute_group_values": {}
    }

    # 1. Models and Explores
    logger.info("Pobieranie modeli (Models)...")
    models = sdk.all_lookml_models()
    
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
                explore_details = sdk.lookml_model_explore(
                    lookml_model_name=model.name,
                    explore_name=explore.name
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

        sa_query = looker_sdk.models.WriteQuery(
            model="system__activity",
            view="dashboard",
            fields=["dashboard.id", "dashboard.title", "dashboard.folder_id", "query.model", "query.view"],
            filters=filters
        )
        response_json = sdk.run_inline_query(result_format="json", body=sa_query)
        raw_data["system_activity_dashboards"] = json.loads(response_json)
    except Exception as e:
        logger.warning(f"Błąd podczas pobierania System Activity: {e}")

    # 3. Dashboards
    logger.info("Pobieranie Dashboardów...")
    dashboards = sdk.all_dashboards(fields="id,title,folder,dashboard_elements(query(model,view),result_maker(query(model,view)))")
    # Zoptymalizuj zapis - zrzucamy tylko te, które się pojawiły w modelu (lub wszystkie)
    if target_model_name != "all":
        sa_dash_ids = {str(d.get("dashboard.id")) for d in raw_data["system_activity_dashboards"]}
        filtered_dashboards = [d for d in dashboards if str(d.id) in sa_dash_ids]
        raw_data["dashboards"] = serialize_looker_obj(filtered_dashboards)
    else:
        raw_data["dashboards"] = serialize_looker_obj(dashboards)

    # 4. Users, Groups, Roles
    logger.info("Pobieranie Użytkowników, Grup i Ról...")
    raw_data["users"] = serialize_looker_obj(sdk.all_users())
    raw_data["groups"] = serialize_looker_obj(sdk.all_groups())
    
    roles = sdk.all_roles()
    raw_data["roles"] = serialize_looker_obj(roles)
    
    logger.info("Pobieranie relacji Role -> Group...")
    for role in roles:
        try:
            r_groups = sdk.role_groups(role_id=role.id)
            raw_data["role_groups"][role.id] = serialize_looker_obj(r_groups)
        except Exception as e:
            logger.warning(f"Błąd podczas pobierania grup dla roli {role.id}: {e}")

    # 5. Security (Model Sets, Permission Sets, User Attributes)
    logger.info("Pobieranie Zestawów Modeli, Uprawnień i Atrybutów Użytkownika...")
    raw_data["model_sets"] = serialize_looker_obj(sdk.all_model_sets())
    raw_data["permission_sets"] = serialize_looker_obj(sdk.all_permission_sets())
    
    user_attributes = sdk.all_user_attributes()
    raw_data["user_attributes"] = serialize_looker_obj(user_attributes)
    
    for ua in user_attributes:
        if not ua.is_system:
            try:
                ua_group_vals = sdk.all_user_attribute_group_values(user_attribute_id=ua.id)
                raw_data["user_attribute_group_values"][ua.id] = serialize_looker_obj(ua_group_vals)
            except Exception as e:
                pass

    # 6. Folders and Folder Accesses
    logger.info("Pobieranie Folderów i ich Uprawnień...")
    folders = sdk.all_folders()
    raw_data["folders"] = serialize_looker_obj(folders)
    
    for folder in folders:
        # Pomiń foldery bez metadata_id
        if folder.content_metadata_id:
            try:
                accesses = sdk.all_content_metadata_accesses(content_metadata_id=folder.content_metadata_id)
                if accesses:
                    raw_data["folder_accesses"][folder.id] = serialize_looker_obj(accesses)
            except Exception as e:
                pass

    # Zapis do pliku
    output_filename = "raw_looker_data.json"
    logger.info(f"Zapisywanie danych do pliku: {output_filename} ...")
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=2)
    logger.info("Pomyślnie zapisano surowe dane!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Looker Raw Data Extractor")
    parser.add_argument("--model", default="all", help="Nazwa konkretnego modelu do ograniczenia ekstrakcji (domyślnie 'all' czyli pobiera całą instancję).")
    args = parser.parse_args()

    extract_raw_data(args.model)
