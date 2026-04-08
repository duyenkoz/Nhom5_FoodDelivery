from app.data.home import get_home_page_data


def _filter_sections(sections, query):
    if not query:
        return sections

    normalized_query = query.lower()
    filtered_sections = []

    for section in sections:
        filtered_items = [
            item
            for item in section["items"]
            if normalized_query in item["name"].lower()
            or normalized_query in item["featured_name"].lower()
            or normalized_query in item["address"].lower()
        ]

        if filtered_items:
            filtered_sections.append({**section, "items": filtered_items})

    return filtered_sections


def get_home_page_context(query=""):
    page = get_home_page_data()
    page["search_query"] = query
    page["sections"] = _filter_sections(page["sections"], query)
    page["results_count"] = sum(len(section["items"]) for section in page["sections"])
    return page
