kind: meson
description: meson test

depends:
- base.bst

sources:
- kind: tar
  directory: Source
  url: project_dir:/files/mesonhello.tar.gz
  ref: dbfa22f02c82c83493596cde465a7ed4c39d8d412da3d8ac3b24c3045781f3b2

variables:
  conf-root: "%{build-root}/Source"
  command-subdir: build
