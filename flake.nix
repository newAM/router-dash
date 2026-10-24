{
  description = "A dashboard for my router";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    treefmt.url = "github:numtide/treefmt-nix";
    treefmt.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = {
    self,
    nixpkgs,
    treefmt,
  }: let
    overlay = final: prev: {
      router-dash = prev.callPackage ./package.nix {
        src = nixpkgs.lib.fileset.toSource {
          root = ./.;
          fileset = nixpkgs.lib.fileset.unions [
            ./router_dash
            ./tests
            ./pyproject.toml
            ./README.md
          ];
        };
      };
    };

    forEachSystem = nixpkgs.lib.genAttrs [
      "aarch64-linux"
      "x86_64-linux"
    ];
    importPkgs = system:
      import nixpkgs {
        inherit system;
        overlays = [overlay];
      };

    treefmtSettings = {
      projectRootFile = "flake.nix";
      programs = {
        alejandra.enable = true;
        prettier.enable = true;
        ruff-format.enable = true;
        taplo.enable = true;
      };
    };
  in {
    overlays = {
      default = overlay;
      router-dash = overlay;
    };

    nixosModules = {
      default = import ./nixos/module.nix;
      router-dash = import ./nixos/module.nix;
    };

    packages = forEachSystem (
      system: let
        pkgs = importPkgs system;
      in {
        inherit (pkgs) router-dash;
        default = pkgs.router-dash;
      }
    );

    formatter = forEachSystem (
      system: (treefmt.lib.evalModule (importPkgs system) treefmtSettings).config.build.wrapper
    );

    devShells = forEachSystem (
      system: let
        pkgs = importPkgs system;
        # router-dash is included (in addition to the working tree, which
        # takes precedence via PYTHONPATH) so that tests can resolve the
        # installed package metadata (e.g. the repository URL).
        # toPythonModule is needed because applications are otherwise
        # excluded from Python environments.  ignoreCollisions resolves
        # the conflict between the package's gunicorn wrapper and the
        # propagated gunicorn package.
        pythonEnv = pkgs.python3.buildEnv.override {
          ignoreCollisions = true;
          extraLibs =
            (with pkgs.python3Packages; [
              authlib
              click
              flask
              flask-session
              flask-wtf
              pytest
              pytest-cov
              pytest-flask
              requests
              ruff
              setuptools
              systemd-python
              ty
            ])
            ++ [(pkgs.python3Packages.toPythonModule pkgs.router-dash)];
        };
      in {
        default = pkgs.mkShell {
          packages = [pythonEnv];
          shellHook = ''
            export PYTHONPATH="$PWD:${pythonEnv}/${pythonEnv.sitePackages}:$PYTHONPATH"
          '';
        };
      }
    );

    checks = forEachSystem (
      system: let
        pkgs = importPkgs system;
      in {
        inherit (pkgs) router-dash;

        formatting = ((treefmt.lib.evalModule pkgs (nixpkgs.lib.recursiveUpdate treefmtSettings
          {
            programs.ruff-check.enable = true;
          }))
          .config
          .build
          .check)
        self;

        nixos-basic = pkgs.callPackage ./nixos/tests/basic.nix {inherit self;};
      }
    );
  };
}
