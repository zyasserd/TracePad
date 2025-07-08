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

      # TODO: understand the diff between the three inputs types
      propagatedBuildInputs = [
        python
      ];

      buildInputs = with pkgs; [
        gtk4
        libadwaita
      ];

      nativeBuildInputs = with pkgs; [
        gobject-introspection
        wrapGAppsHook
      ];

      env = {
        # TODO: remove?
        # required to make the app run wayland
        GDK_BACKEND = "wayland";
        PYTHON_NIX = "${python.interpreter}";
      };

    in {

      # `devShell` or `devShells.default`
      devShell = pkgs.mkShell {
        inherit propagatedBuildInputs nativeBuildInputs buildInputs env;

        packages = [ 

        ];
      };


      packages = rec {
        TracePad = pythonPackages.buildPythonApplication {
          inherit propagatedBuildInputs nativeBuildInputs buildInputs;
          pname = "TracePad";
          version = "1.0.0-beta";
          src = ./.;
          format = "pyproject";

          # env is just for build time; this is to expose in env variables in runtime
          # TODO: understand 
          # https://ryantm.github.io/nixpkgs/languages-frameworks/gnome/
          preFixup = ''
            gappsWrapperArgs+=(
              --prefix PYTHON_NIX : ${env.PYTHON_NIX}
            )
          '';
        };

        default = TracePad;
      };

    }
  );

}