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

      # Propagated dependencies are made available to all downstream dependencies,
      # i.e. all the dependencies of python (including the packages) are added automatically.
      propagatedBuildInputs = [
        python
      ];

      # for simplification, used during run time
      buildInputs = with pkgs; [
        gtk4
        libadwaita
      ];

      # for simplification, used during build time
      nativeBuildInputs = with pkgs; [
        gobject-introspection
        wrapGAppsHook
      ];

      env = {
        PYTHON_NIX = "${python.interpreter}";
      };

    in {

      # `devShell` or `devShells.default`
      devShell = pkgs.mkShell {
        inherit env;

        packages = propagatedBuildInputs ++ buildInputs ++ nativeBuildInputs ++ [ 
        ];

        # Note: pkexec is not available in `nix develop` by default.
        # Adding polkit via Nix provides pkexec, but it lacks the required setuid bit.
        # Workarounds:
        #   - Manually set up pkexec with the correct permissions, OR
        #   - Use direnv to allow the system pkexec to be accessible.

      };


      packages = rec {
        TracePad = pythonPackages.buildPythonApplication {
          inherit propagatedBuildInputs nativeBuildInputs buildInputs;
          pname = "TracePad";
          version = "1.0.0-beta";
          src = ./.;
          format = "pyproject";

          # env is just for build time; this is to expose in env variables in runtime
          # https://ryantm.github.io/nixpkgs/languages-frameworks/gnome/
          preFixup = let
            vars =
              pkgs.lib.strings.concatMapStringsSep
                "\n"
                (name: "  --prefix ${name} : ${env.${name}}")
                (builtins.attrNames env);
          in ''
            gappsWrapperArgs+=(
              ${vars}
            )
          '';
        };

        default = TracePad;
      };

    }
  );

}