kind: manual
depends:
- filename: base/alpine-image.bst
  type: build
sources:
- kind: git
  url: https://gitlab.com/BuildStream/buildstream-sysroots.git
  track: dpkg-build
  ref: ecf14954e4298ce5495f701464339162fad73f30
config:
  install-commands:
  - tar xf dpkg-build-sysroot.tar.xz -C %{install-root} --no-same-owner
  strip-commands:
    # For some reason, the strip commands were hanging...
    - echo "none"
