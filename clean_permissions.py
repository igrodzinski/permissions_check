import json

def clean_permissions_json(input_filepath="permissions_looker_data.json", output_filepath="cleaned_permissions_looker_data.json"):
    print(f"Otwieranie pliku: {input_filepath}...")
    with open(input_filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 1. Zdefiniowanie zbędnych ról
    EXCLUDED_ROLE_NAMES = {
        "admin", "user", "developer", "viewer", "gemini",
        "conversional analytics user", "conversiona analytics agent manager",
        "conversional analytics agent manager"
    }

    roles_to_delete_ids = set()
    for role in data.get("roles", []):
        r_name = str(role.get("name", "")).strip().lower()
        if r_name in EXCLUDED_ROLE_NAMES:
            roles_to_delete_ids.add(str(role.get("id")))
            role["permissions"] = {"models": [], "explores": [], "dashboards": [], "excluded": True}
            
    print(f"Znaleziono {len(roles_to_delete_ids)} ról do wykluczenia.")
    
    # 2. Identyfikacja folderów do zachowania (Shared)
    all_folders = {str(f.get("id")): f for f in data.get("folders", []) if isinstance(f, dict)}
    
    shared_folder_ids = set()
    # Sprawdzamy czy API Lookera wypluło nowe flagi (is_personal)
    has_flags = any("is_personal" in f for f in all_folders.values())
    has_parent_id = any(f.get("parent_id") not in (None, "", "None") for f in all_folders.values())
    
    if has_flags:
        print("Wykryto flagi 'is_personal' w pliku. Wybieram tylko foldery współdzielone (System/Shared)...")
        for fid, f in all_folders.items():
            if not f.get("is_personal") and not f.get("is_personal_descendant"):
                shared_folder_ids.add(fid)
    elif has_parent_id:
        print("Brak flag 'is_personal'. Buduję drzewo 'Shared' na podstawie 'parent_id'...")
        shared_root_ids = {
            fid for fid, f in all_folders.items()
            if str(f.get("name", "")).lower() in ("shared", "shared folders")
        }
        
        def get_subtree(root_ids, folder_map):
            result = set(root_ids)
            added = True
            while added:
                added = False
                for fid, f in folder_map.items():
                    pid = str(f.get("parent_id") or "")
                    if pid in result and fid not in result:
                        result.add(fid)
                        added = True
            return result
            
        shared_folder_ids = get_subtree(shared_root_ids, all_folders)
    else:
        print("UWAGA: Brak flag 'is_personal' oraz brak 'parent_id'. Uruchamiam tryb awaryjny (Fallback)...")
        # Jeśli nie mamy struktury drzewa, dopuszczamy wszystkie jawnie widoczne foldery
        # (ponieważ większość ukrytych folderów personalnych i tak nie trafia do all_folders).
        # Wykluczamy jedynie foldery, które wprost nazywają się "Users" lub "Personal".
        for fid, f in all_folders.items():
            name = str(f.get("name", "")).lower()
            if name not in ("users", "personal"):
                shared_folder_ids.add(fid)

    # Explicitly allow LookML dashboards which have folder_id "lookml"
    shared_folder_ids.add("lookml")

    print(f"Ilość folderów uznanych za bezpieczne (Shared/LookML): {len(shared_folder_ids)}")

    # 3. Zbieramy identyfikatory dozwolonych dashboardów
    allowed_dashboards = set()
    
    # Źródło 1: Zwykłe dashboardy
    for d in data.get("dashboards", []):
        if not isinstance(d, dict): continue
        d_id = str(d.get("id"))
        d_folder = str(d.get("folder_id"))
        if d_folder in shared_folder_ids:
            allowed_dashboards.add(d_id)
            
    # Źródło 2: System Activity Dashboards
    for sa in data.get("system_activity_dashboards", []):
        if not isinstance(sa, dict): continue
        d_id = str(sa.get("dashboard.id"))
        d_folder = str(sa.get("dashboard.folder_id"))
        if d_folder in shared_folder_ids:
            allowed_dashboards.add(d_id)

    print(f"Zidentyfikowano {len(allowed_dashboards)} dozwolonych dashboardów w obszarze Shared/LookML.")
    if len(allowed_dashboards) == 0:
        print("UWAGA: Nie znaleziono żadnego dozwolonego dashboardu! To zepsuje wykres.")
        print(f"Przykładowe id folderów w shared_folder_ids (max 10): {list(shared_folder_ids)[:10]}")
        # Wydrukuj przykładowy folder z system activity
        sample_d = next(iter(data.get("system_activity_dashboards", [])), {})
        print(f"Przykładowy dashboard z System Activity: id={sample_d.get('dashboard.id')}, folder_id={sample_d.get('dashboard.folder_id')}")

    # 4. Wyczyszczenie uprawnień encji w pliku
    for entity_type in ["roles", "groups", "users"]:
        for entity in data.get(entity_type, []):
            if not isinstance(entity, dict) or "permissions" not in entity:
                continue
                
            perms = entity["permissions"]
            
            # Wyczyść przypisania z wykluczonych ról dla grup i userów
            # Uwaga: dziedziczenie już się dokonało w starym pliku, 
            # więc po prostu odfiltrujemy puste role i usuniemy złe dashboardy.
            
            current_dashboards = perms.get("dashboards", [])
            filtered_dashboards = [d for d in current_dashboards if str(d) in allowed_dashboards]
            perms["dashboards"] = filtered_dashboards

    # Zapisz wyczyszczony plik
    print(f"Zapisywanie wyczyszczonego pliku: {output_filepath}...")
    with open(output_filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print("Zakończono pomyślnie!")

if __name__ == '__main__':
    clean_permissions_json()
