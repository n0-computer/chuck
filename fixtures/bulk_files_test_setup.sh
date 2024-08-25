#!/bin/bash

./generate_files.sh 1000 10000 bulk_1k_x_10k
./generate_files.sh 5000 10000 bulk_5k_x_10k
./generate_files.sh 1000 1000000 bulk_1k_x_1m
./generate_files.sh 1000 10000 bulk_mix #1kx10k
./generate_files.sh 1000 1000000 bulk_mix #1kx1m
./generate_files.sh 100 10000000 bulk_mix #100x10m
./generate_files.sh 2 1000000000 bulk_mix #2x1g