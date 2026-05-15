import json
import logging
import argparse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def build_sankey(
    input_file: str,
    output_file: str,
    target_type: str = "user",
    target_models: list = None,
    target_entities: list = None,   # Filtr po nazwie/emailu usera, grupy lub roli
    target_explores: list = None,   # Filtr po nazwie exploracji
    target_dashboards: list = None  # Filtr po tytule dashboardu
):
    """
    Buduje strukturę nodes/links pod wykres Sankey (Plotly).

    target_type        : "user", "group" lub "role"
    target_models      : lista nazw modeli (None = wszystkie)
    target_entities    : lista nazw/emaili encji końcowych (None = wszystkie)
    target_explores    : lista nazw eksploracji (None = wszystkie)
    target_dashboards  : lista tytułów dashboardów (None = wszystkie)
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

    def get_node_index(node_id: str, label: str, type_str: str) -> int:
        nonlocal current_idx
        if node_id not in node_indices:
            node_indices[node_id] = current_idx
            nodes.append({"id": node_id, "label": label, "type": type_str})
            current_idx += 1
        return node_indices[node_id]

    def add_link(source_idx: int, target_idx: int, value: int = 1):
        for l in links:
            if l["source"] == source_idx and l["target"] == target_idx:
                l["value"] += value
                return
        links.append({"source": source_idx, "target": target_idx, "value": value})

    # 1. Lookup: Dashboard id -> title
    dash_details = {}
    for d in raw_data.get("dashboards", []):
        if isinstance(d, dict):
            dash_details[str(d.get("id"))] = d.get("title", f"Dash {d.get('id')}")

    # Lookup: Dashboard id -> [{model, explore}]
    dash_to_explores = {}
    # Lookup odwrotny: "model::explore" -> czy ma jakikolwiek dashboard w datasecie
    explore_has_dashboard = set()
    for sa in raw_data.get("system_activity_dashboards", []):
        if not isinstance(sa, dict): continue
        d_id = str(sa.get("dashboard.id"))
        m    = sa.get("query.model")
        e    = sa.get("query.view")
        dash_to_explores.setdefault(d_id, []).append({"model": m, "explore": e})
        if m and e:
            explore_has_dashboard.add(f"{m}::{e}")

    # Normalizacja filtrów do lowercase sets dla case-insensitive matching
    filter_models    = {m.lower() for m in target_models}    if target_models    else None
    filter_entities  = {e.lower() for e in target_entities}  if target_entities  else None
    filter_explores  = {e.lower() for e in target_explores}  if target_explores  else None
    filter_dashboards = {d.lower() for d in target_dashboards} if target_dashboards else None

    # 2. Iteracja po wybranej encji
    target_list_name = f"{target_type}s"
    target_list = raw_data.get(target_list_name, [])

    if not target_list:
        logger.warning(f"Brak danych dla encji: {target_list_name}")
        return

    for entity in target_list:
        if not isinstance(entity, dict): continue

        # Pomijanie systemowych grup zaczynających się od "4"
        if target_type == "group" and str(entity.get("name", "")).startswith("4"):
            continue

        e_id   = str(entity.get("id"))
        e_name = (
            entity.get("display_name")
            or entity.get("name")
            or entity.get("email")
            or f"{target_type.capitalize()} {e_id}"
        )

        # Filtr po encji docelowej (user/group/role)
        if filter_entities and e_name.lower() not in filter_entities:
            continue

        perms = entity.get("permissions", {})
        if not perms:
            continue

        ent_idx = get_node_index(f"{target_type}_{e_id}", e_name, target_type)

        # -- Ścieżka pełna: Model -> Explore -> Dashboard -> Wariant --
        for d_id in perms.get("dashboards", []):
            d_title = dash_details.get(str(d_id), f"Dashboard {d_id}")

            # Filtr po tytule dashboardu
            if filter_dashboards and d_title.lower() not in filter_dashboards:
                continue

            dash_explores = dash_to_explores.get(str(d_id), [])

            # Filtr po modelu
            if filter_models:
                dash_explores = [x for x in dash_explores if x["model"] and x["model"].lower() in filter_models]

            # Filtr po eksploracji
            if filter_explores:
                dash_explores = [x for x in dash_explores if x["explore"] and x["explore"].lower() in filter_explores]

            if not dash_explores:
                continue

            dash_idx = get_node_index(f"dash_{d_id}", d_title, "dashboard")
            add_link(dash_idx, ent_idx)

            for ex in dash_explores:
                m_name    = ex["model"]
                e_name_str = ex["explore"]
                m_idx = get_node_index(f"model_{m_name}", m_name, "model")
                e_idx = get_node_index(f"explore_{m_name}_{e_name_str}", e_name_str, "explore")
                add_link(m_idx, e_idx)
                add_link(e_idx, dash_idx)

        # -- Ścieżka bez dashboardu: Model -> Explore -> Wariant --
        # Rysowana TYLKO gdy dana Eksploracja faktycznie nie ma żadnego dashboardu
        # w całym datasecie (nie mylić z dashboardem, który nie przeszedł filtra!)
        for explore_key in perms.get("explores", []):
            try:
                m_name, e_name_str = explore_key.split("::")
            except ValueError:
                continue

            # Pomiń jeśli ta exploracja ma dashboardy – w takim przypadku
            # link pokaże się przez ścieżkę pełną; tu nie chcemy duplikatów
            # ani węzłów niezwiązanych z aktywnym filtrem
            if explore_key in explore_has_dashboard:
                continue

            if filter_models and m_name.lower() not in filter_models:
                continue
            if filter_explores and e_name_str.lower() not in filter_explores:
                continue
            # Jeśli filtrujemy po dashboardzie, pomijamy fallback (nie ma tu dashboardu)
            if filter_dashboards:
                continue

            m_idx = get_node_index(f"model_{m_name}", m_name, "model")
            e_idx = get_node_index(f"explore_{m_name}_{e_name_str}", e_name_str, "explore")
            add_link(m_idx, e_idx)
            add_link(e_idx, ent_idx)

    # 3. Zapis
    output_data = {"nodes": nodes, "links": links}
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    logger.info(f"Gotowe! Zapisano dane Sankey do {output_file} (Węzłów: {len(nodes)}, Krawędzi: {len(links)})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Builder danych do wykresu Sankey")
    parser.add_argument("--input",      default="permissions_looker_data.json")
    parser.add_argument("--output",     default="sankey_data.json")
    parser.add_argument("--type",       choices=["user", "group", "role"], default="user",
                        help="Typ encji docelowej: 'user', 'group' lub 'role' (domyślnie 'user')")
    parser.add_argument("--models",     "--model",     dest="models",     nargs="+",
                        help="Filtruj po nazwach modeli")
    parser.add_argument("--entities",   "--entity",    dest="entities",   nargs="+",
                        help="Filtruj po nazwach/emailach encji docelowych (user/group/role)")
    parser.add_argument("--explores",   "--explore",   dest="explores",   nargs="+",
                        help="Filtruj po nazwach eksploracji")
    parser.add_argument("--dashboards", "--dashboard", dest="dashboards", nargs="+",
                        help="Filtruj po tytułach dashboardów")

    import sys
    args, unknown = parser.parse_known_args()

    build_sankey(
        input_file=args.input,
        output_file=args.output,
        target_type=args.type,
        target_models=args.models,
        target_entities=args.entities,
        target_explores=args.explores,
        target_dashboards=args.dashboards
    )
