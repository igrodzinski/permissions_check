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
    target_entities: list = None,
    target_explores: list = None,
    target_dashboards: list = None
):
    """
    Buduje strukturę nodes/links pod wykres Sankey (Plotly).

    Logika przepływu:
      Model -> Explore -> Dashboard -> Entity (user/group/role)

    Połączenie jest rysowane TYLKO wtedy gdy:
      1. Dashboard jest w liście permissions.dashboards encji (dostęp przez folder)
      2. Eksploracja buduje ten dashboard (system_activity_dashboards)
      3. Eksploracja jest w liście permissions.explores encji (dostęp przez rolę/model_set)

    Wszystkie 3 warunki muszą być spełnione jednocześnie.
    """
    logger.info(f"Budowanie Sankey: plik={input_file}, typ={target_type}")
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

    # --- Lookups ---
    # Dashboard id -> title
    dash_title = {}
    for d in raw_data.get("dashboards", []):
        if isinstance(d, dict):
            dash_title[str(d.get("id"))] = d.get("title", f"Dash {d.get('id')}")

    # Dashboard id -> set of "model::explore" keys (jakie exploracje go budują)
    dash_to_explore_keys = {}
    for sa in raw_data.get("system_activity_dashboards", []):
        if not isinstance(sa, dict): continue
        d_id = str(sa.get("dashboard.id"))
        m = sa.get("query.model")
        e = sa.get("query.view")
        if m and e:
            dash_to_explore_keys.setdefault(d_id, set()).add(f"{m}::{e}")

    # --- Normalizacja filtrów (case-insensitive) ---
    filter_models     = {x.lower() for x in target_models}     if target_models     else None
    filter_entities   = {x.lower() for x in target_entities}   if target_entities   else None
    filter_explores   = {x.lower() for x in target_explores}   if target_explores   else None
    filter_dashboards = {x.lower() for x in target_dashboards} if target_dashboards else None

    # --- Główna pętla po encjach ---
    target_list = raw_data.get(f"{target_type}s", [])
    if not target_list:
        logger.warning(f"Brak danych dla encji: {target_type}s")
        return

    for entity in target_list:
        if not isinstance(entity, dict): continue

        # Pomiń systemowe grupy
        if target_type == "group" and str(entity.get("name", "")).startswith("4"):
            continue

        e_id   = str(entity.get("id"))
        e_name = (
            entity.get("display_name")
            or entity.get("name")
            or entity.get("email")
            or f"{target_type.capitalize()} {e_id}"
        )

        # Filtr po encji
        if filter_entities and e_name.lower() not in filter_entities:
            continue

        perms = entity.get("permissions", {})
        if not perms:
            continue

        # Precalculated explore keys dla tej encji: "model::explore"
        entity_explore_keys = set(perms.get("explores", []))
        entity_dash_ids     = set(str(x) for x in perms.get("dashboards", []))

        ent_idx = None  # tworzymy węzeł encji dopiero gdy mamy coś do połączenia

        for d_id in entity_dash_ids:
            d_title_str = dash_title.get(d_id, f"Dashboard {d_id}")

            # Filtr po dashboardzie
            if filter_dashboards and d_title_str.lower() not in filter_dashboards:
                continue

            # Kluczowy INTERSECT:
            # Eksploracje budujące dashboard ∩ eksploracje, do których encja ma dostęp
            all_dash_explores = dash_to_explore_keys.get(d_id, set())
            accessible_explores = entity_explore_keys & all_dash_explores

            if not accessible_explores:
                continue

            # Filtrowanie po modelu / exploracji (opcjonalne filtry użytkownika)
            filtered_explores = set()
            for key in accessible_explores:
                m_name, e_name_str = key.split("::", 1)
                if filter_models and m_name.lower() not in filter_models:
                    continue
                if filter_explores and e_name_str.lower() not in filter_explores:
                    continue
                filtered_explores.add(key)

            if not filtered_explores:
                continue

            # Tworzymy węzeł encji przy pierwszym rzeczywistym połączeniu
            if ent_idx is None:
                ent_idx = get_node_index(f"{target_type}_{e_id}", e_name, target_type)

            dash_idx = get_node_index(f"dash_{d_id}", d_title_str, "dashboard")
            add_link(dash_idx, ent_idx)

            for key in filtered_explores:
                m_name, e_name_str = key.split("::", 1)
                m_idx = get_node_index(f"model_{m_name}", m_name, "model")
                e_idx = get_node_index(f"explore_{m_name}_{e_name_str}", e_name_str, "explore")
                add_link(m_idx, e_idx)
                add_link(e_idx, dash_idx)

    # --- Zapis ---
    output_data = {"nodes": nodes, "links": links}
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    logger.info(f"Gotowe! Zapisano {output_file} (Węzłów: {len(nodes)}, Krawędzi: {len(links)})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Builder danych do wykresu Sankey")
    parser.add_argument("--input",       default="permissions_looker_data.json")
    parser.add_argument("--output",      default="sankey_data.json")
    parser.add_argument("--type",        choices=["user", "group", "role"], default="user",
                        help="Typ encji: 'user', 'group' lub 'role'")
    parser.add_argument("--models",      "--model",     dest="models",     nargs="+",
                        help="Filtruj po nazwach modeli")
    parser.add_argument("--entities",    "--entity",    dest="entities",   nargs="+",
                        help="Filtruj po nazwach/emailach encji (user/group/role)")
    parser.add_argument("--explores",    "--explore",   dest="explores",   nargs="+",
                        help="Filtruj po nazwach eksploracji")
    parser.add_argument("--dashboards",  "--dashboard", dest="dashboards", nargs="+",
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
