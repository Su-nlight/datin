import { Connection, clusterApiUrl, Keypair, PublicKey } from '@solana/web3.js';
import { Metaplex, keypairIdentity } from '@metaplex-foundation/js';
import fs from 'fs';

async function main() {
  try {
  
    const keypairFile = fs.readFileSync(process.env.HOME + '/.config/solana/id.json', 'utf-8');
    const keypair = Keypair.fromSecretKey(new Uint8Array(JSON.parse(keypairFile)));
    
    const connection = new Connection(clusterApiUrl('devnet'));
    const metaplex = new Metaplex(connection);
    metaplex.use(keypairIdentity(keypair));

    const mintAddress = new PublicKey('8KjhqrhweSshVkSswXmQ394wcPgMjf1Uc98W22CQhPNM');

    const { nft } = await metaplex.nfts().create({
      uri: 'https://your-metadata-uri.json', 
      name: 'Your Token Name',
      symbol: 'YTN',
      sellerFeeBasisPoints: 0, 
      updateAuthority: keypair, 
      mintAuthority: keypair,
      tokenStandard: 4,
      mint: mintAddress,
    });

    console.log('Metadata created successfully');
    console.log('Metadata address:', nft.address.toString());
  } catch (error) {
    console.error('Error creating metadata:', error);
  }
}

main();
