## Renova Artifact Service (matches workspace-service layout)

- Stores CAM v1 artifacts per `workspace_id`
- Full JSON Patch history + provenance
- Emits `artifact.created|updated|patched` to `renova.events`

### Run local
```bash
uvicorn app.main:app --reload --port 9011
```
