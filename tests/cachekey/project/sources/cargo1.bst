kind: import
sources:
- kind: local
  path: files/local
- kind: cargo
  url: upstream:crates
  ref:
  - name: foo
    version: 1.0
    sha: thisisthecratesha
