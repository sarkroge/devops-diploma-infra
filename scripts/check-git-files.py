#!/usr/bin/env python3
"""Reject credential/state paths in the Git index before publishing."""
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[1]
paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
forbidden = re.compile(
    r'(^|/)(\.secrets|\.terraform|__pycache__)/'
    r'|\.tfstate($|\.)|\.(tfplan|plan)$|\.tfvars(\.json)?$'
    r'|(^|/)backend(\.[^/]*)?\.hcl$|(^|/).*[-]key\.json$'
    r'|\.(pem|key)$|(^|/)kubeconfig[^/]*$|\.pyc$'
)
bad = [path for path in paths if path and forbidden.search(path)]
if bad:
    print('Do not publish these tracked files:')
    print('\n'.join(bad))
    raise SystemExit(1)
print('Git index: no Terraform state, variable files or credential paths tracked.')
