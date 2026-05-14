import json
import argparse
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def build_sankey(input_file: str, output_file: str, include_users: bool, target_models: list = None):
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Plik {input_file} nie istnieje. Najpierw wygeneruj go przez skrypt extract_raw_data.py")
        return

    nodes = []
    links = []
    node_indices = {}

    def get_node_index(n_id: str, label: str, n_type: str) -> int:
        if n_id not in node_indices:
            idx = len(nodes)
            nodes.append({
                "id": n_id,
                "label": label,
                "type": n_type
            })
            node_indices[n_id] = idx
        return node_indices[n_id]

    def add_link(source_idx: int, target_idx: int, value: int = 1):
        # Prevent duplicate links
        for link in links:
            if link["source"] == source_idx and link["target"] == target_idx:
                return
        links.append({"source": source_idx, "target": target_idx, "value": value})

    # Dictionaries for quick lookup
    groups_dict = {str(g.get("id")): g.get("name", f"Group {g.get('id')}") for g in raw_data.get("groups", [])}
    
    # Przetwarzanie Dashboardów do słownika, by szybko pobierać ich folder_id
    dash_to_folder = {}
    dash_names = {}
    for d in raw_data.get("dashboards", []):
        d_id = str(d.get("id"))
        
        # Ochrona przed rzutowaniem None na string "None"
        f_id = d.get("folder_id") or d.get("folder", {}).get("id")
        if f_id:
            dash_to_folder[d_id] = str(f_id)
            
        dash_names[d_id] = d.get("title", f"Dash {d_id}")
        
    # Słownik dostępów folderów
    folder_to_groups = {}
    for folder_id, accesses in raw_data.get("folder_accesses", {}).items():
        folder_to_groups[str(folder_id)] = [str(a.get("group_id")) for a in accesses if a.get("group_id")]

    used_groups = set()

    # 1. Models & Explores
    for model in raw_data.get("models", []):
        model_name = model.get("name")
        
        # Filtrowanie po wybranych modelach
        if target_models and model_name not in target_models:
            continue
            
        model_idx = get_node_index(f"model_{model_name}", model_name, "model")
        
        # Pobieramy explores dla danego modelu ze słownika `explores` lub `model.explores`
        model_explores = raw_data.get("explores", {}).get(model_name, [])
        for explore in model_explores:
            explore_name = explore.get("name")
            explore_id = f"explore_{model_name}_{explore_name}"
            explore_idx = get_node_index(explore_id, explore_name, "explore")
            
            # Link Model -> Explore
            add_link(model_idx, explore_idx)

    # 2. System Activity -> łączymy Explores z Dashboardami
    for sa_row in raw_data.get("system_activity_dashboards", []):
        model_name = sa_row.get("query.model")
        view_name = sa_row.get("query.view")
        dash_id = str(sa_row.get("dashboard.id", ""))
        
        if not model_name or not view_name or not dash_id:
            continue
            
        explore_id = f"explore_{model_name}_{view_name}"
        if explore_id in node_indices:
            explore_idx = node_indices[explore_id]
            
            d_title = dash_names.get(dash_id, sa_row.get("dashboard.title", f"Dash {dash_id}"))
            
            d_folder = dash_to_folder.get(dash_id)
            if not d_folder:
                sa_folder = sa_row.get("dashboard.folder_id")
                d_folder = str(sa_folder) if sa_folder else ""
                
            dash_node_id = f"dash_{dash_id}"
            dash_idx = get_node_index(dash_node_id, d_title, "dashboard")
            
            # Link Explore -> Dashboard
            add_link(explore_idx, dash_idx)
            
            # 3. Z Dashboardu (przez folder) -> Do Grupy
            if d_folder and d_folder in folder_to_groups:
                for group_id in folder_to_groups[d_folder]:
                    g_name = groups_dict.get(group_id, f"Group {group_id}")
                    g_node_id = f"group_{group_id}"
                    g_idx = get_node_index(g_node_id, g_name, "group")
                    
                    # Link Dashboard -> Group
                    add_link(dash_idx, g_idx)
                    used_groups.add(group_id)

    # 4. (Opcjonalnie) Użytkownicy -> dołączani tylko do przypisanych wcześniej grup
    if include_users:
        logger.info("Dołączam użytkowników do wykresu Sankey...")
        for u in raw_data.get("users", []):
            u_group_ids = [str(g_id) for g_id in u.get("group_ids", [])]
            # Sprawdź, czy użytkownik ma grupę, która bierze udział w przepływie
            intersecting_groups = used_groups.intersection(u_group_ids)
            if intersecting_groups:
                u_id = str(u.get("id"))
                u_name = u.get("display_name") or u.get("email") or f"User {u_id}"
                u_idx = get_node_index(f"user_{u_id}", u_name, "user")
                
                for g_id in intersecting_groups:
                    g_idx = node_indices[f"group_{g_id}"]
                    # Link Group -> User
                    add_link(g_idx, u_idx)

    # Przygotowanie wyjścia i optymalizacja JSON (oczyszczenie z węzłów, które nigdzie nie prowadzą? W sumie sankey sobie poradzi, ale dla czystości można by to zrobić).
    # Zostawmy, ponieważ build mapuje z góry do dołu.
    
    sankey_data = {
        "nodes": nodes,
        "links": links
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(sankey_data, f, ensure_ascii=False, indent=2)
        
    logger.info(f"Gotowe! Zapisano dane Sankey do {output_file} (Węzłów: {len(nodes)}, Krawędzi: {len(links)})")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Builder danych do wykresu Sankey na podstawie surowego pliku Lookera")
    parser.add_argument("--input", default="raw_looker_data.json", help="Ścieżka do pliku wejściowego (domyślnie raw_looker_data.json)")
    parser.add_argument("--output", default="sankey_data.json", help="Ścieżka do zapisu (domyślnie sankey_data.json)")
    parser.add_argument("--include_users", action="store_true", help="Dodaje na końcu strumienie łączące Grupy z poszczególnymi Użytkownikami")
    parser.add_argument("--models", nargs="+", help="Filtruj wygenerowany wykres Sankeya dla wybranych modeli (np. --models model1 model2)")
    args = parser.parse_args()

    build_sankey(args.input, args.output, args.include_users, args.models)
