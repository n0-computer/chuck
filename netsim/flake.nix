{
  description = "A flake to set up netsim temporary environment";

  inputs = { utils.url = "github:numtide/flake-utils"; };
  outputs = { self, nixpkgs, utils }:
    utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };

        ovsScripts = "${pkgs.openvswitch}/share/openvswitch/scripts";

        pyPkgs = with pkgs.python3Packages; [
          pyshark
          drawsvg
          dpkt
          humanfriendly
          mininet-python
        ];

        netsim = pkgs.writeScriptBin "netsim" ''
          #!/bin/sh

          echo "Running with PYTHONPATH: $PYTHONPATH"
          sudo PYTHONPATH=$PYTHONPATH python3 main.py $@
        '';

      in {
        devShell = pkgs.mkShell {
          buildInputs = with pkgs;
            [ inetutils mininet openvswitch iperf tshark python3 netsim ]
            ++ pyPkgs;

          shellHook = ''
            export OVS_DBDIR=$(pwd)
            sudo ${ovsScripts}/ovs-ctl start \
              --db-file="$OVS_DBDIR/conf.db" \
              --system-id=random

            sudo ovs-vsctl show

            cleanup() {
              sudo ${ovsScripts}/ovs-ctl stop
              sudo rm $OVS_DBDIR/conf.db
            }
            trap cleanup EXIT
          '';
        };
      });
}
