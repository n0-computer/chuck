rm -rf logs/*
rm -rf report/*
rm -rf viz/*
sudo mn --clean
sudo kill -9 $(pgrep iroh)
sudo kill -9 $(pgrep derper)
sudo kill -9 $(pgrep ovs)


# we use shorter interface names due to size constraints, which means we need to have a custom cleanup too
echo "Cleaning up interfaces"
links=$(ip link show | egrep -o '([-_.[:alnum:]]+-e[[:digit:]]+)')
for link in $links; do
    # Run your command with $link as a parameter
    echo "Deleting $link"
    # Example command: sudo ip link delete $link
    sudo ip link delete $link
done