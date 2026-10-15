import json

import httpx
import pytest

from prompt_registry.models import Source
from prompt_registry.parsers import parse_source
from prompt_registry.sync import fetch_one


def source(adapter: str) -> Source:
    return Source(
        id="ecommerce", name="Ecommerce", adapter=adapter,
        url="https://raw.githubusercontent.com/example/repo/main/data/catalog.json",
        homepage="https://github.com/example/repo", minimum_items=1,
    )


def test_ecommerce_preserves_sets_variants_and_real_edit_references():
    record = {
        "id": "ec-1", "slug": "serum", "title": "Serum", "prompt": "Make a campaign set.",
        "translations": {"zh": {"title": "精华液", "description": "产品套图"}},
        "mode": "product-edit", "model": "gpt-image-2", "license": "CC-BY-4.0",
        "author": {"name": "Studio"}, "publishedAt": "2026-07-20",
        "variants": [
            {"id": "hero", "title": "HERO", "prompt": "Edit the supplied product.",
             "aspectRatio": "5:8", "sample": {"before": "assets/before.png", "after": "assets/after.png", "license": "CC-BY-4.0"}},
            {"id": "scene", "title": "SCENE", "prompt": "Make the scene.",
             "sample": {"after": "assets/scene.png"}},
        ],
    }
    items = parse_source(source("ecommerce-json"), json.dumps({"prompts": [record]}).encode())
    assert len(items) == 3
    assert len({item["id"] for item in items}) == 3
    assert items[0]["prompt"] == record["prompt"]
    assert items[0]["title"] == "精华液 · 套图方案"
    assert items[0]["coverUrl"] == ""
    assert "imageCount" not in items[0]
    assert items[1]["coverUrl"].endswith("/main/assets/after.png")
    assert items[1]["referenceImageUrls"] == ["https://raw.githubusercontent.com/example/repo/main/assets/before.png"]
    assert items[2]["referenceImageUrls"] == []
    assert items[1]["imageSize"] == "5:8"
    assert items[1]["imageMode"] == "edit"
    assert items[1]["author"] == "Studio"
    assert "CC-BY-4.0" in items[1]["description"]
    assert items[1]["sourceUrl"] == "https://github.com/example/repo/blob/main/catalog/ec-1-serum.md"
    record["title"] = "Renamed"
    record["variants"].reverse()
    reordered = parse_source(source("ecommerce-json"), json.dumps({"prompts": [record]}).encode())
    assert {item["id"] for item in reordered} == {item["id"] for item in items}
    second = {**record, "id": "ec-2"}
    both = parse_source(source("ecommerce-json"), json.dumps({"prompts": [record, second]}).encode())
    assert len(both) == 6


def test_kero_filters_non_ecommerce_and_keeps_full_workflow():
    common = {"prompt": "Product prompt", "source": {"path": "prompts/visuals.md", "anchor": "product"}}
    payload = {
        "prompts": [
            {**common, "id": "kv", "title": "10 屏产品 KV", "category": "ecommerce-poster",
             "tags": ["产品"], "images": ["assets/kv.png"], "models": ["Nano Banana"]},
            {**common, "id": "birthday", "title": "Birthday", "category": "ecommerce-poster", "tags": ["电商、海报与社交视觉"]},
            {**common, "id": "copy", "title": "Copy", "category": "copywriting", "tags": ["电商"]},
            {**common, "id": "product-ad-4x4-storyboard", "title": "产品广告分镜", "category": "image-video"},
        ],
        "workflows": [
            {**common, "id": "detail-workflow", "title": "详情页工作流", "type": "workflow",
             "category": "ecommerce-visual", "contentPath": "content/workflows/detail/workflow.md", "prompt": ""},
            {**common, "id": "market", "title": "Market", "category": "market-automation"},
        ],
    }
    requested = []
    workflow = "# Description\n\n````text\nFirst stage.\n```json\n{}\n```\nLast stage.\n````\n"

    def respond(request):
        requested.append(request.url.path)
        if request.url.path.endswith("catalog.json"):
            return httpx.Response(200, json=payload)
        return httpx.Response(200, text=workflow)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        items = fetch_one(client, source("kero-json"))
    assert len(items) == 3
    assert requested == ["/example/repo/main/data/catalog.json", "/example/repo/main/content/workflows/detail/workflow.md"]
    assert items[0]["coverUrl"] == "https://raw.githubusercontent.com/example/repo/main/assets/kv.png"
    assert items[0]["referenceImageUrls"] == []
    assert items[0]["sourceUrl"].endswith("/prompts/visuals.md#product")
    assert "CC BY-NC 4.0" in items[0]["description"]
    assert items[0]["author"] == "KeRo AI Prompt Library / Youks7"
    assert items[-1]["prompt"] == "First stage.\n```json\n{}\n```\nLast stage."
    assert "电商工作流" in items[-1]["tags"]

    def failed_workflow(request):
        return httpx.Response(200, json=payload) if request.url.path.endswith("catalog.json") else httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(failed_workflow)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            fetch_one(client, source("kero-json"))


@pytest.mark.parametrize("adapter", ["ecommerce-json", "kero-json"])
def test_ecommerce_rejects_invalid_catalog(adapter):
    with pytest.raises(ValueError):
        parse_source(source(adapter), b"[]")
