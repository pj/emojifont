{
  description = "Development environment for emojifont (SBIX meme font tools)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
        };
      in
      {
        packages.default = pkgs.python3Packages.buildPythonApplication {
          pname = "emojifont";
          version = "0.1.1";
          pyproject = true;
          src = self;
          build-system = [ pkgs.python3Packages.flit-core ];
          dependencies = with pkgs.python3Packages; [
            fonttools
            pillow
          ];
        };

        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            go
            gopls
            gotools
            python3
            uv
          ];

          shellHook = ''
            echo "emojifont development environment ready!"
            echo "uv version: $(uv --version)"
          '';
        };
      }
    );
}

