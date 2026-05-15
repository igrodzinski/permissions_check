import json
import logging
import argparse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def build_sankey(input_file: str, output_file: str, target_type: str = "user", target_models: list = None):
    """
    Buduje strukturę nodes/links pod wykres Sankey (Plotly).
    target_type: "user", "group", "role"
    """
    logger.info(f"Rozpoczynam budowę danych Sankey z pliku: {input_file} (Typ docelowy: {target_type})")
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Nie znaleziono pliku {input_file}! Uruchom extract_raw_data.py najpierw.")
        return

    nodes = []
    links = []
    
    node_indices = {}
    current_idx = 0
    
    # helper
    def get_node_index(node_id: str, label: str, type_str: str) -> int:
        nonlocal current_idx
        if node_id not in node_indices:
            node_indices[node_id] = current_idx
            nodes.append({
                "id": node_id,
                "label": label,
                "type": type_str
            })
            current_idx += 1
        return node_indices[node_id]
        
    def add_link(source_idx: int, target_idx: int, value: int = 1):
        for l in links:
            if l["source"] == source_idx and l["target"] == target_idx:
                l["value"] += value
                return
        links.append({"source": source_idx, "target": target_idx, "value": value})

    # 1. Master lookups for Dashboards & Explores
    dash_details = {}
    for d in raw_data.get("dashboards", []):
        if isinstance(d, dict):
            dash_details[str(d.get("id"))] = d.get("title", f"Dash {d.get('id')}")
            
    dash_to_explores = {}
    for sa in raw_data.get("system_activity_dashboards", []):
        if not isinstance(sa, dict): continue
        d_id = str(sa.get("dashboard.id"))
        if d_id not in dash_to_explores:
            dash_to_explores[d_id] = []
        dash_to_explores[d_id].append({
            "model": sa.get("query.model"),
            "explore": sa.get("query.view")
        })

    # 2. Iteracja po wybranym wariancie docelowym
    target_list_name = f"{target_type}s" # "user" -> "users"
    target_list = raw_data.get(target_list_name, [])
    
    if not target_list:
        logger.warning(f"Brak danych dla encji: {target_list_name}")
        return

    for entity in target_list:
        if not isinstance(entity, dict): continue
        
        # Ominięcie systemowych grup
        if target_type == "group" and str(entity.get("name", "")).startswith("4"):
            continue
            
        e_id = str(entity.get("id"))
        e_name = entity.get("name") or entity.get("display_name") or entity.get("email") or f"{target_type.capitalize()} {e_id}"
        
        perms = entity.get("permissions", {})
        if not perms:
            continue
            
        # Opcja 1: Pełna ścieżka do dashboardów: Model -> Explore -> Dashboard -> Wariant
        for d_id in perms.get("dashboards", []):
            dash_explores = dash_to_explores.get(str(d_id), [])
            
            # Filtrowanie modeli jeśli podano
            if target_models:
                dash_explores = [x for x in dash_explores if x["model"] in target_models]
                
            if not dash_explores: 
                continue
                
            # Wariant Node
            ent_idx = get_node_index(f"{target_type}_{e_id}", e_name, target_type)
            
            # Dash Node
            d_title = dash_details.get(str(d_id), f"Dashboard {d_id}")
            dash_idx = get_node_index(f"dash_{d_id}", d_title, "dashboard")
            
            # Link Dashboard -> Wariant
            add_link(dash_idx, ent_idx)
            
            for ex in dash_explores:
                m_name = ex["model"]
                e_name_str = ex["explore"]
                
                m_idx = get_node_index(f"model_{m_name}", m_name, "model")
                e_idx = get_node_index(f"explore_{m_name}_{e_name_str}", e_name_str, "explore")
                
                add_link(m_idx, e_idx)
                add_link(e_idx, dash_idx)
                
        # Opcja 2 (Opcjonalna dla kompletności): Jeśli wariant ma dostęp do Explore, ale nie ma z tego dashboardu
        # Pokażemy wtedy ścieżkę Explore -> Wariant.
        for explore_key in perms.get("explores", []):
            try:
                m_name, e_name_str = explore_key.split("::")
            except ValueError:
                continue
                
            if target_models and m_name not in target_models:
                continue
                
            m_idx = get_node_index(f"model_{m_name}", m_name, "model")
            e_idx = get_node_index(f"explore_{m_name}_{e_name_str}", e_name_str, "explore")
            ent_idx = get_node_index(f"{target_type}_{e_id}", e_name, target_type)
            
            add_link(m_idx, e_idx)
            # Rysujemy bezpośrednie wejście do Exploracji by widzieć pełen zakres dostępu do danych
            add_link(e_idx, ent_idx)

    # 3. Zapis
    output_data = {
        "nodes": nodes,
        "links": links
    }
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
        
    logger.info(f"Gotowe! Zapisano dane Sankey do {output_file} (Węzłów: {len(nodes)}, Krawędzi: {len(links)})")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Builder danych do wykresu Sankey")
    parser.add_argument("--input", default="permissions_looker_data.json", help="Ścieżka do pliku (domyślnie permissions_looker_data.json)")
    parser.add_argument("--output", default="sankey_data.json", help="Ścieżka do zapisu (domyślnie sankey_data.json)")
    parser.add_argument("--type", choices=["user", "group", "role"], default="user", help="Zakończenie strumieni (domyślnie 'user')")
    parser.add_argument("--models", "--model", dest="models", nargs="+", help="Filtruj wygenerowany wykres dla wybranych modeli")
    
    import sys
    args, unknown = parser.parse_known_args()

    build_sankey(args.input, args.output, args.type, args.models)
