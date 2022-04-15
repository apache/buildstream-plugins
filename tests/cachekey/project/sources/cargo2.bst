kind: import
sources:
- kind: local
  path: files/local
- kind: cargo
  url: upstream:crates
  vendor-dir: ponies
  cargo-lock: Pony.lock
  ref:
  - name: foo
    version: 1.0
    sha: thisisthecratesha
