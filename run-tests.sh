#!/bin/bash
# Kör samma tester som GitHub Actions — utan Docker
set -e
cd ""/usr/bin"
source venv/bin/activate

echo '=== Unit tests ==='
pytest tests/unit/test_docs.py tests/unit/test_utils.py tests/unit/test_qc.py -v

echo '=== Agent-mail tests ==='
cd clio-agent-mail && pytest tests/ -v
