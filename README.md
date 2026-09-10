# ArtLens Agent

An evidence-aware art interpretation prototype with museum image retrieval, image-pair verification, and conversational explanations.

[中文安装说明](README.zh-CN.md)

## Version 0.1.2

- Upload JPEG, PNG or WebP images in a responsive Chinese workspace.
- Retrieve five museum candidates using CLIP embeddings and cosine similarity.
- Compare the upload against the leading local reference image with a vision API when the score and margin gates pass.
- Display a likely-match artwork card with museum author/date, verification details, retrieval margin and measured processing time.
- Keep observations, sourced metadata and tentative interpretations distinct in the model instructions.
- Render model headings and lists using text nodes; never execute model-generated HTML.
- Ask follow-up questions within a short-lived in-memory session.

## Run locally

Python 3.11 recommended:

```sh
python -m venv .venv
# Activate the environment for your OS, then:
pip install -r requirements.txt
cp .env.example .env
# Fill VISION_API_KEY, VISION_BASE_URL and VISION_MODEL.
python -m uvicorn artlens.main:app --host 127.0.0.1 --port 8000
```

Windows commands are in the Chinese guide. Open http://127.0.0.1:8000.

Optional museum indexing (stop the server first):

```sh
pip install -r requirements-retrieval.txt
python -m scripts.build_index --limit 200
```

Images and weights are downloaded separately, not bundled. The gallery is a limited Art Institute of Chicago subset, not a worldwide artwork database.

## Interpretation of results

An empty threshold setting now falls back to 0.95 minimum score and 0.03 top-two margin. These are uncalibrated routing defaults, not a confidence estimate. A passing gate triggers one extra vision request. A valid same-work response with at least two concrete matches and no reported differences yields `likely_match`. Missing references, invalid responses or inconclusive comparisons retain an uncertain result. A different-work verdict yields unknown. This is fallible model review, not artwork authentication.

The API key stays on the server; uploads are sent to the configured provider. Sessions are memory-only, bounded to 20, expire after an hour and disappear on restart. Public hosting is not included and requires authentication, request limits and resource controls. Publishing on GitHub does not host the Python backend.

## Validation and research

Python behavior tests and JS renderer checks are included. Model verification tests use mocks; they do not measure real recognition accuracy. The user reported the prior image-pair flow working locally; this update has no fresh real-provider or browser visual validation. No benchmark accuracy is claimed.

```sh
pip install pytest
python -m pytest -q
node tests/test_render.cjs
```

See [research plan](docs/RESEARCH_PLAN.md). Music recognition and source-level factual checking remain future work. This is a bounded tool workflow, not autonomous general-purpose planning.

Code: MIT. Museum description text retains CC BY 4.0 attribution; other metadata and public-domain images follow the museum terms. Model weights retain their own terms.
