# COBOL Parser Tool (ProLeap + cb2xml)

A tiny FastAPI microservice that exposes:
- `POST /parse`           → ProLeap program parsing (AST/ASG as JSON)
- `POST /copybook_to_xml` → cb2xml conversion of copybooks → XML

## Prereqs (choose one path)

### A) Docker-only (recommended)
- You **do not** need Python or Java on host; Docker image ships JRE + your JARs.
- Place the following in `jars/` (next to this README):
  - `proleap-cli.jar` — your small wrapper CLI around the ProLeap library that prints JSON.
  - `cb2xml.jar` — download a release JAR (e.g., 0.95.x).
- Build & run:
  ```bash
  docker build -t renova/proleap-cb2xml:latest .
  docker run --rm -p 8080:8080 renova/proleap-cb2xml:latest
