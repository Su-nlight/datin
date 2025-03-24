import json
import os

def split_json_files(input_dir, output_dir, chunk_size=510):
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Iterate over all JSON files in the input directory
    for filename in os.listdir(input_dir):
        if filename.endswith('.json'):
            input_file = os.path.join(input_dir, filename)
            
            # Read JSON file
            with open(input_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Ensure it's a list
            if not isinstance(data, list):
                print(f"Skipping {filename}: JSON file must contain a list of objects.")
                continue
            
            # If the file has less than or equal to chunk_size entries, keep the original name
            if len(data) <= chunk_size:
                output_file = os.path.join(output_dir, filename)
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4)
            else:
                # Split data into chunks
                for i in range(0, len(data), chunk_size):
                    chunk = data[i:i + chunk_size]
                    output_file = os.path.join(output_dir, f'{os.path.splitext(filename)[0]}_chunk_{i // chunk_size + 1}.json')
                    
                    # Write chunk to new file
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(chunk, f, indent=4)
    
    print("Successfully split all JSON files in the input directory.")

# Example usage
input_directory = ["enterprise", "ics", "mobile"]  # Change this to your input directory

for dirs in input_directory:
    print(f"Mitre_Stix/filtered-{dirs}", f"Mitre_Stix/chunked-{dirs}")
    split_json_files(f"Mitre_Stix/filtered-{dirs}", f"Mitre_Stix/chunked-{dirs}")
