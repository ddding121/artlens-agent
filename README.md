# ArtLens Agent

An evidence-aware art interpretation research prototype: upload an artwork, retrieve museum candidates, and explore visual observations, sourced metadata, and explicitly tentative interpretations.

[中文安装与运行说明](README.zh-CN.md)

## Implemented

- FastAPI backend and responsive Chinese web workspace.
- OpenAI-compatible vision provider adapter (user-supplied credentials).
- Optional CLIP image-to-image retrieval over public-domain Art Institute of Chicago paintings.
- Museum source links, conservative unknown handling, and short-lived follow-up sessions.
- Reproducible collection indexing and retrieval evaluation scripts.

## Quick start

Python 3.11 recommended. Create and activate a virtual environment, then:

```sh
pip install -r requirements.txt
cp .env.example .env
# Configure a vision-capable API in .env.
python -m uvicorn artlens.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. See the Chinese guide for Windows commands and optional indexing.

## Research status

Version 0.1 is a bounded tool workflow, not yet a free-planning agent. Similarity is not calibrated confidence. Candidate retrieval does not verify authorship, and generated interpretation is not authenticated artist intent. Unknown handling is conservative by default. Prompt rules reduce but cannot eliminate hallucinations. No measured identification accuracy or admissions outcome is claimed.

Real-provider integration and full CLIP indexing need validation with the user's credentials and network. Automated tests exercise local behavior and mocked model responses only. Music recognition, second-stage visual verification, source-level factual checking, and controlled ablation experiments are planned, not implemented.

See [research plan](docs/RESEARCH_PLAN.md) and [validation notes](docs/VALIDATION.md).

## Privacy and deployment

Uploaded images are normalized and kept in bounded in-process sessions; analysis sends them to the configured model provider. Credentials remain server-side. Local use only in this release; public hosting needs authentication, request-body limits, rate limiting, and resource controls. Publishing this repository does not deploy its Python backend.

Code: MIT. Museum assets and model weights retain their own terms and are not bundled.
