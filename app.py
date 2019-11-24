import hashlib
import platform
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()


class Wallet(BaseModel):
    index: str
    value: int


class Wallets(BaseModel):
    wallets: Dict[str, Wallet]
    length: int

    def find_by_index(self, wallet_index: str) -> Optional[Wallet]:
        return self.wallets.get(wallet_index)

    def add_wallet(self, wallet: Wallet) -> None:
        if self.wallets.get(wallet.index):
            return None

        self.wallets[wallet.index] = wallet
        self.length += 1

        return None


WALLETS = Wallets.parse_file('database/wallets.json')

node_wallet_index = platform.node()
WALLETS.add_wallet(Wallet(index=node_wallet_index, value=0))


class Transaction(BaseModel):
    amount: int = 0
    index: int
    recipient: str
    sender: str

    def commit(self) -> None:
        sender_wallet = WALLETS.find_by_index(self.sender)
        recipient_wallet = WALLETS.find_by_index(self.recipient)

        sender_wallet.value -= self.amount  # type: ignore
        recipient_wallet.value += self.amount  # type: ignore


class Block(BaseModel):
    index: int
    length: int
    previous_hash: str
    proof: Optional[int]
    timestamp: datetime
    transactions: List[Transaction]

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.json(sort_keys=True).encode()).hexdigest()

    def close(self) -> None:
        for transaction in self.transactions:
            transaction.commit()


class Chain(BaseModel):
    length: int
    blocks: List[Block]

    @property
    def last_block(self) -> Block:
        return self.blocks[-1]

    def proof_of_work(self) -> int:
        '''Simple Proof of Work Algorithm:

            - Find a number p' such that hash(pp') contains leading 4 zeroes
            - Where p is the previous proof, and p' is the new proof

        Returns:
            int: Proof number
        '''

        last_proof = self.last_block.proof
        last_hash = self.last_block.hash

        proof = 0
        while not self.validate_proof(last_proof, proof, last_hash):  # type: ignore
            proof += 1
        return proof

    @staticmethod
    def validate_proof(prev_proof: int, current_proof: int, prev_hash: str) -> bool:
        '''Validates the Proof

        Args:
            prev_proof (int): Previous Proof
            current_proof (int): Current Proof
            prev_hash (str): The hash of the Previous Block

        Returns:
            bool: True if correct, False if not.
        '''

        guess = f'{prev_proof}{current_proof}{prev_hash}'.encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:4] == "0000"

    def validate_chain(self) -> bool:
        prev_block = self.blocks[0]
        for block in self.blocks[1:]:
            if block.previous_hash != prev_block.hash:
                return False
            if not self.validate_proof(prev_block.proof,  # type: ignore
                                       block.proof,  # type: ignore
                                       prev_block.hash):
                return False
            prev_block = block
        return True


CHAIN = Chain.parse_file('database/blockchain.json')

BLOCK = Block(
    index=CHAIN.length,
    length=0,
    previous_hash=CHAIN.last_block.hash,
    proof=None,
    timestamp=datetime.now(timezone.utc),
    transactions=[],
)


@app.get('/api/wallets', response_model=Wallets)
def wallets() -> Wallets:
    return WALLETS


@app.get('/api/wallets/{username}', response_model=Optional[Wallet])
def wallet_by_username(username: str) -> Optional[Wallet]:
    return WALLETS.find_by_index(hashlib.sha256(username.encode()).hexdigest())


@app.get('/api/wallets/{id}', response_model=Optional[Wallet])
def wallet_by_id(id: str) -> Optional[Wallet]:
    return WALLETS.find_by_index(id)


@app.post('/api/wallets', response_model=Wallet)
def wallet(username: str, value: int = 1500) -> Wallet:

    wallet = Wallet(
        index=hashlib.sha256(username.encode()).hexdigest(),
        value=value,
    )

    WALLETS.add_wallet(wallet)

    with open('database/wallets.json', 'w') as f:
        f.write(WALLETS.json(sort_keys=True, indent=4))

    return wallet


@app.get('/api/chain', response_model=Chain)
def chain() -> Chain:
    return CHAIN


@app.get('/api/chain/blocks/current/transactions', response_model=List[Transaction])
def current_transactions() -> List[Transaction]:
    return BLOCK.transactions


@app.get('/api/chain/blocks/{id}/transactions', response_model=List[Transaction])
def transactions_by_id(id: int) -> List[Transaction]:
    if id > len(CHAIN.blocks):
        raise HTTPException(
            detail='Block not found',
            status_code=404,
        )
    return CHAIN.blocks[id].transactions


@app.post('/api/chain/blocks/transactions', response_model=Transaction)
def transactions(transaction: Transaction) -> Transaction:
    BLOCK.transactions.append(transaction)
    transaction.index = BLOCK.length
    BLOCK.length += 1
    return transaction


@app.get('/api/chain/blocks', response_model=List[Block])
def blocks() -> List[Block]:
    return CHAIN.blocks


@app.get('/api/chain/blocks/{id}', response_model=Block)
def blocks_by_id(id: int) -> Block:
    if id > len(CHAIN.blocks):
        raise HTTPException(
            detail='Block not found',
            status_code=404,
        )
    return CHAIN.blocks[id]


@app.get('/api/mine', response_model=Block)
def mine() -> Block:
    global BLOCK
    if not BLOCK.transactions:
        raise HTTPException(
            status_code=204, detail='No transactions in current block')

    tax = Transaction(
        index=BLOCK.length,
        recipient=node_wallet_index,
        sender='none',
        amount=1,
    )

    BLOCK.transactions.append(tax)

    BLOCK.close()
    BLOCK.proof = CHAIN.proof_of_work()
    CHAIN.blocks.append(BLOCK)
    CHAIN.length += 1

    if not CHAIN.validate_chain():
        raise HTTPException(status_code=599, detail='Chain is not valid')

    with open('database/blockchain.json', 'w') as f:
        f.write(CHAIN.json(sort_keys=True, indent=4))

    with open('database/wallets.json', 'w') as f:
        f.write(WALLETS.json(sort_keys=True, indent=4))

    BLOCK = Block(
        index=CHAIN.length,
        length=0,
        previous_hash=BLOCK.hash,
        proof=None,
        timestamp=datetime.now(),
        transactions=[],
    )
    return CHAIN.last_block
