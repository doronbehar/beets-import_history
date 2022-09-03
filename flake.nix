{
  description = "A beets plugin recording where albums where imported from";
  inputs.flake-utils.url = "github:numtide/flake-utils";

  outputs = { self, nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in {
        devShell = pkgs.mkShell {
          inherit (pkgs.beets)
            buildInputs
            checkInputs
          ;
          nativeBuildInputs = pkgs.beets.nativeBuildInputs ++ [
            pkgs.python3.pkgs.jedi-language-server
          ];
          propagatedBuildInputs = [
            pkgs.beets
          ];
        };
      }
    );
}
