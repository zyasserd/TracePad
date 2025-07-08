{
  description = "A python template";
  
  inputs = {
    nixpkgs.url = "nixpkgs/nixos-unstable";
    
    # in the nix global registry: `github:numtide/flake-utils`
    utils.url = "flake-utils";
  };

  outputs = { self, nixpkgs, utils }: utils.lib.eachDefaultSystem (system:
    let
      pkgs = import nixpkgs {
        inherit system;
      };

      python = pkgs.python3.withPackages (ps: with ps; [
        pygobject3
        pygobject-stubs # for autocompletion
        pycairo
        evdev
        psutil
        setuptools
      ]);
      pythonPackages = python.pkgs;

      propagatedBuildInputs = [
        python
      ];

      nativeBuildInputs = with pkgs; [
        libadwaita
        gobject-introspection
        wrapGAppsHook
      ];

      env = {
        GDK_BACKEND = "wayland"; # required to make the app run wayland
        PYTHON_NIX = "${python.interpreter}";
      };

    in {

      # `devShell` or `devShells.default`
      devShell = pkgs.mkShell {
        inherit propagatedBuildInputs nativeBuildInputs env;

        packages = [ 

        ];
      };


      packages = rec {
        TracePad = pythonPackages.buildPythonApplication {
          inherit propagatedBuildInputs nativeBuildInputs;
          pname = "TracePad";
          version = "1.0.0-beta";
          src = ./.;
          format = "pyproject";

          # env is just for build time; this is to expose in env variables in runtime
          # https://ryantm.github.io/nixpkgs/languages-frameworks/gnome/
          preFixup = ''
            gappsWrapperArgs+=(
              --prefix GDK_BACKEND : ${env.GDK_BACKEND}
              --prefix PYTHON_NIX : ${env.PYTHON_NIX}
            )
          '';
        };

        default = TracePad;
      };

    }
  );

}