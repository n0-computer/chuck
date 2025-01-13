#!/bin/bash

# Ensure correct usage
if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <number of iterations> <command>"
    exit 1
fi

# Assign inputs
N=$1
shift
command="$@"

# Run the command N times
for ((i = 1; i <= N; i++)); do
    echo "Running command (iteration $i/$N)..."
    $command
    exit_code=$?

    if [ $exit_code -ne 0 ]; then
        echo "Command failed on iteration $i with exit code $exit_code"
        exit $exit_code
    fi
done

echo "Command completed successfully in all $N iterations."