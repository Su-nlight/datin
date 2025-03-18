import { Connection, clusterApiUrl, Keypair, PublicKey } from '@solana/web3.js';
import { Metaplex, keypairIdentity } from '@metaplex-foundation/js';
import fs from 'fs';

async function main() {
  try {
    // Load your keypair from the default Solana CLI location
    // This is typically located at ~/.config/solana/id.json
    const keypairFile = fs.readFileSync(process.env.HOME + '/.config/solana/id.json', 'utf-8');
    const keypair = Keypair.fromSecretKey(new Uint8Array(JSON.parse(keypairFile)));

    // Connect to devnet
    const connection = new Connection(clusterApiUrl('devnet'));
    const metaplex = new Metaplex(connection);
    metaplex.use(keypairIdentity(keypair));

    // Your token mint address - replace with your actual token address
    const mintAddress = new PublicKey('8KjhqrhweSshVkSswXmQ394wcPgMjf1Uc98W22CQhPNM');
    
    // Create metadata for your token
    const { nft } = await metaplex.nfts().create({
      uri: 'https://your-metadata-uri.json', // URL to your metadata JSON
      name: 'Your Token Name',
      symbol: 'YTN',
      sellerFeeBasisPoints: 0, // No royalties
      updateAuthority: keypair, 
      mintAuthority: keypair,
      tokenStandard: 4, // This is for Fungible tokens
      mint: mintAddress,
    });

    console.log('Metadata created successfully');
    console.log('Metadata address:', nft.address.toString());
  } catch (error) {
    console.error('Error creating metadata:', error);
  }
}

main();