kind: manual

depends:
- filename: base/alpine-image.bst

config:
  install-commands:
  - |
    install -D -m 0755 ninja %{install-root}%{bindir}/ninja

sources:
- kind: zip
  url: https://github.com/ninja-build/ninja/releases/download/v1.9.0/ninja-linux.zip
  ref: 1b1235f2b0b4df55ac6d80bbe681ea3639c9d2c505c7ff2159a3daf63d196305
  base-dir: ''
