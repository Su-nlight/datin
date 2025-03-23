import pandas as pd
files=["exploits","shellcodes"]
# List of columns to remove
columns_to_remove = [
    'verified', 
    'date_added', 
    'date_updated', 
    'screenshot_url', 
    'application_url', 
    'source_url'
]
for file in files: 
    # Read the CSV file
    df = pd.read_csv(f'ExploitDB/files_{file}.csv')
    # Remove the specified columns
    df_filtered = df.drop(columns=columns_to_remove)
    # Save to CSV file
    df_filtered.to_csv(f'ExploitDB/filtered_{file}.csv', index=False)
print("Data has been saved to CSV format.")
