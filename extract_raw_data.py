import looker_sdk
import api
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
    logger.info("Inicjalizacja przez zewnętrzny plik api...")
    
    raw_data = {
        "metadata": {
            "target_model": target_model_name
        },
        "users": [],
        "groups": [],
        "models": [],
        "explores": {},
        "dashboards": [],
        "system_activity_dashboards": [],
        "folders": [],
        "folder_accesses": {},
        "user_attributes": [],
        "user_attribute_group_values": {}
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

        sa_query = looker_sdk.models.WriteQuery(
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

    # 4. Users and Groups
    logger.info("Pobieranie Użytkowników i Grup...")
    raw_data["users"] = serialize_looker_obj(api.sdk.all_users(fields="id,email,display_name,group_ids,role_ids"))
    raw_data["groups"] = serialize_looker_obj(api.sdk.all_groups(fields="id,name"))

    # 5. Access Grants Mapping (User Attributes)
    logger.info("Pobieranie Atrybutów Użytkownika dla Access Grants...")
    try:
        user_attributes = api.sdk.all_user_attributes()
        # Filtrujemy już w Pythonie obiekty z is_system == False i zapisujemy tylko potrzebne pola
        filtered_ua = [{"id": ua.id, "name": ua.name} for ua in user_attributes if not getattr(ua, 'is_system', False)]
        raw_data["user_attributes"] = filtered_ua
        
        for ua_dict in filtered_ua:
            try:
                ua_group_vals = api.sdk.all_user_attribute_group_values(user_attribute_id=ua_dict["id"])
                raw_data["user_attribute_group_values"][ua_dict["id"]] = serialize_looker_obj(ua_group_vals)
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
