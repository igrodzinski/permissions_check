import looker_sdk
import json
import logging
import argparse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_extraction(target_model_name, users_map=False, show_users_in_groups=False, show_groups_in_groups=False):
    # INSTRUCTION FROM USER:
    path_api = "" # Uzupełnione ręcznie
    sdk = looker_sdk.init40(path_api)
    
    nodes = {}
    edges = []

    def add_node(id_val, label, node_type, properties=None):
        node_id = f"{node_type}_{id_val}"
        if node_id not in nodes:
            node = {"id": node_id, "label": label, "type": node_type}
            if properties:
                node.update(properties)
            nodes[node_id] = node
        return node_id

    def add_edge(source, target, edge_type, properties=None):
        edge = {"source": source, "target": target, "type": edge_type}
        if properties:
            edge.update(properties)
        edges.append(edge)

    logger.info(f"Extracting for model(s): {target_model_name}")

    # 1. Map Model -> Explores -> Access Grants
    logger.info("Fetching LookML models...")
    models = sdk.all_lookml_models(fields="name,explores")
    
    if target_model_name != "all":
        target_models = [m for m in models if m.name == target_model_name]
        if not target_models:
            logger.error(f"Model '{target_model_name}' not found.")
            return
    else:
        target_models = models

    explores_set = set()
    target_model_names = {m.name for m in target_models}

    for target_model in target_models:
        model_node = add_node(target_model.name, target_model.name, "model")

        for explore in target_model.explores or []:
            explore_id = f"{target_model.name}_{explore.name}"
            explore_node = add_node(explore_id, explore.name, "explore")
            add_edge(model_node, explore_node, "has_explore")
            explores_set.add(explore_id)

            try:
                explore_details = sdk.lookml_model_explore(
                    lookml_model_name=target_model.name,
                    explore_name=explore.name,
                    fields="name,required_access_grants" # Note: older Looker SDKs might ignore this field if not present in the model
                )

                # Use getattr to prevent AttributeError if the SDK version does not support required_access_grants
                grants = getattr(explore_details, "required_access_grants", [])
                for grant in grants:
                    grant_node = add_node(grant, grant, "access_grant")
                    add_edge(explore_node, grant_node, "requires_access_grant")
            except looker_sdk.error.SDKError as e:
                logger.warning(f"Could not fetch details for explore {explore.name} in model {target_model.name}: {e}")
            except AttributeError as e:
                logger.warning(f"AttributeError while parsing explore {explore.name}: {e}. Ensure your Looker SDK supports this property.")

    # 2. Fetch all dashboards and map to explores & folders using System Activity
    logger.info("Fetching Dashboards via System Activity...")
    folder_to_dashboards = {}
    
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
        sa_data = json.loads(response_json)

        for row in sa_data:
            d_id = str(row.get("dashboard.id", ""))
            d_title = row.get("dashboard.title", d_id)
            d_folder = row.get("dashboard.folder_id")
            q_model = row.get("query.model")
            q_view = row.get("query.view")

            if d_id and q_model in target_model_names:
                explore_node_id = f"{q_model}_{q_view}"
                if explore_node_id in explores_set:
                    dash_node = add_node(d_id, d_title, "dashboard")
                    add_edge(explore_node_id, dash_node, "used_in_dashboard")

                    if d_folder:
                        if d_folder not in folder_to_dashboards:
                            folder_to_dashboards[d_folder] = []
                        if d_id not in folder_to_dashboards[d_folder]:
                            folder_to_dashboards[d_folder].append(d_id)
    except Exception as e:
        logger.warning(f"Failed to query System Activity for dashboards: {e}")

    # 3. Pre-fetch all Groups so we have accurate names
    logger.info("Fetching Groups...")
    groups = sdk.all_groups()
    for group in groups:
        add_node(group.id, group.name, "group")

    # 4. Get Permission Structure (Roles, Model Sets)
    logger.info("Fetching Model Sets and Roles...")
    model_sets = sdk.all_model_sets()
    for mset in model_sets:
        # Check if the model set includes any of our target models
        included_models = [m for m in (mset.models or []) if m in target_model_names]
        if included_models:
            mset_node = add_node(mset.id, mset.name, "model_set")
            for m in included_models:
                add_edge(mset_node, f"model_{m}", "includes_model")

    roles = sdk.all_roles()
    for role in roles:
        role_node = add_node(role.id, role.name, "role")
        if role.model_set:
            mset_node = f"model_set_{role.model_set.id}"
            if mset_node in nodes: # Link if model set contains our target model
                add_edge(role_node, mset_node, "has_model_set")
                
        # Link Groups to Roles
        try:
            role_groups = sdk.role_groups(role_id=role.id)
            for rg in role_groups:
                group_node = add_node(rg.id, rg.name, "group")
                add_edge(group_node, role_node, "has_role")
        except Exception as e:
            logger.warning(f"Could not fetch groups for role {role.name}: {e}")

    # 5. Dashboard access mapping directly via Folders
    logger.info("Fetching Folder Access to link Groups directly to Dashboards...")
    for folder_id, dash_ids in folder_to_dashboards.items():
        try:
            folder = sdk.folder(folder_id)
            content_meta_id = folder.content_metadata_id
            access_list = sdk.all_content_metadata_accesses(content_metadata_id=content_meta_id)

            for access in access_list:
                if access.group_id:
                    group_node = add_node(access.group_id, f"Group {access.group_id}", "group")
                    for d_id in dash_ids:
                        add_edge(f"dashboard_{d_id}", group_node, "has_dashboard_access")
                elif access.user_id and users_map:
                    user_node = add_node(access.user_id, f"User {access.user_id}", "user")
                    for d_id in dash_ids:
                        add_edge(f"dashboard_{d_id}", user_node, "has_dashboard_access")
        except Exception as e:
            logger.warning(f"Could not fetch access for folder {folder_id}: {e}")

    # 6. Users in Groups (Inline mapping)
    if show_users_in_groups:
        logger.info("Fetching users for groups...")
        # Get all current group IDs
        group_ids = [node["id"].split("_")[1] for node in nodes.values() if node["type"] == "group"]
        for group_id in group_ids:
            try:
                users = sdk.all_group_users(group_id=int(group_id))
                user_names = [u.display_name or u.email or f"User {u.id}" for u in users]
                if user_names:
                    nodes[f"group_{group_id}"]["members"] = user_names
            except Exception as e:
                logger.warning(f"Could not fetch users for group {group_id}: {e}")

    # 7. Groups in Groups
    if show_groups_in_groups:
        logger.info("Fetching group hierarchy (groups in groups)...")
        group_ids = [node["id"].split("_")[1] for node in nodes.values() if node["type"] == "group"]
        for group_id in group_ids:
            try:
                subgroups = sdk.all_group_groups(group_id=int(group_id))
                for sg in subgroups:
                    sg_node = add_node(sg.id, sg.name, "group")
                    add_edge(f"group_{group_id}", sg_node, "contains_group")
            except Exception as e:
                logger.warning(f"Could not fetch subgroups for group {group_id}: {e}")

    # 8. Users map (separate nodes)
    if users_map:
        logger.info("Fetching Users...")
        users = sdk.all_users()
        for user in users:
            user_label = user.display_name or user.email or f"User {user.id}"
            user_node = add_node(user.id, user_label, "user")

            if user.group_ids:
                for gid in user.group_ids:
                    group_node = add_node(gid, f"Group {gid}", "group")
                    add_edge(user_node, group_node, "in_group")

            if user.role_ids:
                for rid in user.role_ids:
                    role_node = add_node(rid, f"Role {rid}", "role")
                    add_edge(user_node, role_node, "has_role")

    # 9. Access Grants Mapping via User Attributes
    logger.info("Fetching User Attributes to map Access Grant satisfactions...")
    try:
        user_attributes = sdk.all_user_attributes()
        for ua in user_attributes:
            if not ua.is_system:
                ua_node = add_node(ua.id, f"UA: {ua.name}", "user_attribute")
                
                # Group mappings
                group_values = sdk.all_user_attribute_group_values(user_attribute_id=ua.id)
                for gv in group_values:
                    if gv.group_id:
                        group_node = add_node(gv.group_id, f"Group {gv.group_id}", "group")
                        add_edge(group_node, ua_node, "has_attribute_value", {"value": gv.value})
                
    except Exception as e:
        logger.warning(f"Could not fetch User Attributes: {e}")

    graph_data = {
        "nodes": list(nodes.values()),
        "edges": edges
    }

    output_file = f"looker_graph_{target_model_name}.json"
    with open(output_file, "w") as f:
        json.dump(graph_data, f, indent=4)
    logger.info(f"Graph data successfully saved to {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Looker Permissions Graph Extractor")
    parser.add_argument("--model", default="all", help="Target LookML model name to extract (e.g., 'mobile'). Default is 'all'.")
    parser.add_argument("--users_map", action="store_true", help="Include users in the map as separate nodes (True/False)")
    parser.add_argument("--show_users_in_groups", action="store_true", help="Append user names to Group nodes")
    parser.add_argument("--show_groups_in_groups", action="store_true", help="Map nested group relationships")
    args = parser.parse_args()

    run_extraction(args.model, args.users_map, args.show_users_in_groups, args.show_groups_in_groups)
