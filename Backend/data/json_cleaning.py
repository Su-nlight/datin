import json
import os
from typing import List, Dict


def load_json_file(file_path: str) -> Dict:
    with open(file_path, 'r') as file:
        return json.load(file)


def filter_data(data: Dict) -> List[Dict]:
    required_keys = ['id', 'name', 'description', 'type', 'created', 'modified', 'external_references']
    filtered_data = []

    for item in data.get('objects', []):
        # Skip attack-pattern types AND skip items without name or description
        if item.get('type') != 'attack-pattern' and 'name' in item and 'description' in item:
            filtered_item = {key: item[key] for key in required_keys if key in item}
            filtered_data.append(filtered_item)

    return filtered_data


def save_json_file(data: List[Dict], output_file_path: str) -> None:
    with open(output_file_path, 'w') as file:
        json.dump(data, file, indent=4)
    print(f"Filtered data saved to {output_file_path}")


def process_folder(input_folder: str, output_folder: str) -> None:
    # Create output folder if it doesn't exist
    os.makedirs(output_folder, exist_ok=True)

    # Get all JSON files in the input folder
    file_count = 0
    for filename in os.listdir(input_folder):
        if filename.endswith('.json'):
            input_path = os.path.join(input_folder, filename)
            output_path = os.path.join(output_folder, filename)

            try:
                # Load and filter the data
                data = load_json_file(input_path)
                filtered_data = filter_data(data)

                # Save the filtered data with the same filename
                save_json_file(filtered_data, output_path)
                file_count += 1
            except Exception as e:
                print(f"Error processing {filename}: {str(e)}")

    print(f"Processed {file_count} files from {input_folder} to {output_folder}")


# new comments here
folders=("enterprise", "mobile", "ics")

for x in folders:
    process_folder(f"Mitre_Stix/{x}-attack", f"Mitre_Stix/filtered-{x}")