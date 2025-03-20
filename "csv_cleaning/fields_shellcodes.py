import pandas as pd

df = pd.read_csv('files_shellcodes.csv')

columns_to_remove = [
    'verified', 
    'date_added', 
    'date_updated', 
    'screenshot_url', 
    'application_url', 
    'source_url'
]

df_filtered = df.drop(columns=columns_to_remove)

df_filtered.to_csv('files_shellcodes_filtered.txt', sep='\t', index=False)

with open('files_shellcodes_formatted.txt', 'w') as f:
    f.write(df_filtered.to_string(index=False))

with open('files_shellcodes_custom.txt', 'w') as f:
    
    f.write('\t'.join(df_filtered.columns) + '\n')
    f.write('-' * 80 + '\n')  
    
    
    for _, row in df_filtered.iterrows():
        f.write('\t'.join(str(val) for val in row.values) + '\n')

print("Data has been saved to text files in three different formats.")
print("Choose the one that works best for your needs.")