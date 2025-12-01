#!/bin/bash

# mosaic.sh - Mosaic acquisition script using tomoscan mosaic command
# Parameters are passed from the Python GUI

# Check if all required parameters are provided
if [ $# -lt 4 ]; then
    echo "Error: Missing parameters!"
    echo "Usage: $0 <h_steps> <v_steps> <h_step_size> <v_step_size> [tomoscan_prefix]"
    echo "Example: $0 3 3 0.2 0.2 32id:TomoScan:"
    exit 1
fi

# Read parameters from command line arguments
H_STEPS=$1
V_STEPS=$2
H_STEP_SIZE=$3
V_STEP_SIZE=$4
TOMOSCAN_PREFIX=${5:-"32id:TomoScan:"}  # Default prefix if not provided

echo "Starting mosaic acquisition with parameters:"
echo "Grid size: ${H_STEPS}x${V_STEPS}"
echo "Step sizes: X=${H_STEP_SIZE}mm, Y=${V_STEP_SIZE}mm"
echo "Tomoscan prefix: ${TOMOSCAN_PREFIX}"
echo "Total scans: $((H_STEPS * V_STEPS))"

# Run the tomoscan mosaic command
echo "Executing tomoscan mosaic command..."

tomoscan mosaic \
    --scan-type Mosaic \
    --tomoscan-prefix "${TOMOSCAN_PREFIX}" \
    --horizontal-steps ${H_STEPS} \
    --vertical-steps ${V_STEPS} \
    --horizontal-step-size ${H_STEP_SIZE} \
    --vertical-step-size ${V_STEP_SIZE} \
    --horizontal-start 0 \
    --vertical-start 0 \
    --verbose

# Check if the command was successful
if [ $? -eq 0 ]; then
    echo "Mosaic acquisition completed successfully!"
else
    echo "Error: Mosaic acquisition failed!"
    exit 1
fi
