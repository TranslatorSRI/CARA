from pathlib import Path
import reasoner_pydantic
import requests
import json

HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}


def test_query(session):
    host_url = "http://127.0.0.1:8080/aragorn/query"
    print(f"host_url: {host_url}")

    query = reasoner_pydantic.message.Query.parse_obj(
        {
            "message": {
                "query_graph": {
                    "nodes": {"n1": {"ids": ["MONDO:0009061"]}, "n0": {"categories": ["biolink:ChemicalEntity"]}},
                    "edges": {"e0": {"subject": "n0", "object": "n1", "predicates": ["biolink:treats"], "knowledge_type": "inferred"}},
                }
            }
        }
    )

    response = requests.post(url=host_url, headers=HEADERS, data=query.json())
    assert response.status_code == 200
    response_json = response.json()
    print(f"response_json: {response_json}")
