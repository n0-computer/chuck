mkdir -p logs
mkdir -p report
mkdir -p data
mkdir -p keys
mkdir -p bins
mkdir -p viz
cd data
rm -f 1G.bin
rm -f 100M.bin
for i in {1..10}; do
    cat ../../fixtures/10MiB.car >> 100M.bin
done
for i in {1..10}; do
    cat 100M.bin >> 1G.bin
done
cp ../../fixtures/key.pem ../bins/key.pem
cp ../../fixtures/cert.pem ../bins/cert.pem
cp ../../fixtures/relay.config.toml relay.config.toml
cp ../../fixtures/direct_relay.cfg direct_relay.cfg
cp ../../fixtures/relay.direct.config.toml relay.direct.config.toml
cp ../../fixtures/1MB.bin 1MB.bin
cp ../../fixtures/dns.test.cfg dns.test.cfg
cp ../../fixtures/relay.cfg relay.cfg
cp ../../fixtures/test.certificate.crt certificate.crt
cp ../../fixtures/test.certificate.private.key certificate.key
cp ../../fixtures/relay.cfg relay.cfg
cp ../../fixtures/n_runs.sh ../bins/n_runs.sh
cp ../../fixtures/hello.bin hello.bin
