#!/bin/bash

# Check if the correct number of arguments are provided
if [ "$#" -ne 3 ]; then
    echo "Usage: $0 <number_of_files> <file_size_in_bytes> <output_folder>"
    exit 1
fi

# Assign arguments to variables
NUMBER_OF_FILES=$1
FILE_SIZE=$2
OUTPUT_FOLDER=$3

# Create the output folder if it doesn't exist
mkdir -p "$OUTPUT_FOLDER"

# Generate a random 4-character string
RANDOM_STRING=$(LC_ALL=C tr -dc 'a-zA-Z0-9' < /dev/urandom | head -c 4)

# Generate the files
for (( i=1; i<=$NUMBER_OF_FILES; i++ ))
do
    # Generate a file with the specified size
    dd if=/dev/urandom of="$OUTPUT_FOLDER/file_${RANDOM_STRING}_$i.bin" bs=$FILE_SIZE count=1
done

echo "Generated $NUMBER_OF_FILES files of size $FILE_SIZE bytes in $OUTPUT_FOLDER with prefix file_$RANDOM_STRING"