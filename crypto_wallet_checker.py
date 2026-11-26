#!/usr/bin/env python3
"""crypto_wallet_checker.py

Prüft Krypto-Wallet-Adressen auf Guthaben und ermittelt die Währung.

Unterstützte Chains (native Guthaben):
  Bitcoin, Ethereum, BNB (BSC), Polygon, Avalanche, Arbitrum, Optimism,
  Fantom, Litecoin, Dogecoin, Solana, Ripple, Cardano, Tron, Bitcoin Cash,
  Cosmos, Algorand, Stellar, Tezos, NEAR, Aptos, Sui, TON, Polkadot (Erkennung)

EVM-Adressen (0x...) werden automatisch auf ALLEN EVM-Chains geprüft,
da das Adressformat identisch ist.

Token: Für Ethereum werden einige gängige ERC-20 geprüft; für Solana SPL
und Tron TRC-20 werden vorhandene Token-Konten aufgelistet.

Verwendung:
    python3 crypto_wallet_checker.py <adresse>
    python3 crypto_wallet_checker.py --file adressen.txt
    python3 crypto_wallet_checker.py --file adressen.txt --human
"""

import sys
import re
import json
import time
import random
import argparse
import urllib.request
import urllib.error


# ---------------------------------------------------------------------------
# HTTP-Hilfen
# ---------------------------------------------------------------------------
def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "crypto-wallet-checker/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return None, str(e)


def http_post_json(url, payload, timeout=20):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "User-Agent": "crypto-wallet-checker/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return None, str(e)


def rpc_call(rpcs, method, params):
    """Versucht mehrere RPC-Endpunkte; gibt (status, result) zurück."""
    for rpc in rpcs:
        st, tx = http_post_json(rpc, {"jsonrpc": "2.0", "method": method, "params": params, "id": 1})
        if st == 200:
            try:
                d = json.loads(tx)
                if "result" in d and d.get("result") is not None:
                    return st, d["result"]
            except Exception:
                pass
    return None, None


# ---------------------------------------------------------------------------
# EVM-Chains (native Balance via eth_getBalance)
# ---------------------------------------------------------------------------
EVM_CHAINS = [
    ("Ethereum", "ETH", ["https://cloudflare-eth.com", "https://ethereum-rpc.publicnode.com"]),
    ("BNB Smart Chain", "BNB", ["https://bsc-dataseed.binance.org", "https://bsc-rpc.publicnode.com"]),
    ("Polygon", "MATIC", ["https://polygon-rpc.com", "https://polygon-bor-rpc.publicnode.com"]),
    ("Avalanche C-Chain", "AVAX", ["https://api.avax.network/ext/bc/C/rpc"]),
    ("Arbitrum One", "ETH", ["https://arb1.arbitrum.io/rpc", "https://arbitrum-one-rpc.publicnode.com"]),
    ("Optimism", "ETH", ["https://mainnet.optimism.io", "https://optimism-rpc.publicnode.com"]),
    ("Fantom", "FTM", ["https://rpc.ftm.tools", "https://fantom-rpc.publicnode.com"]),
    ("Base", "ETH", ["https://mainnet.base.org", "https://base-rpc.publicnode.com"]),
    ("Gnosis", "xDAI", ["https://rpc.gnosischain.com"]),
    ("Celo", "CELO", ["https://forno.celo.org"]),
]


def check_evm_address(address):
    """Prüft eine 0x-Adresse auf allen EVM-Chains. Gibt Liste von (chain, symbol, balance)."""
    out = []
    for name, sym, rpcs in EVM_CHAINS:
        st, res = rpc_call(rpcs, "eth_getBalance", [address, "latest"])
        if res is not None:
            try:
                bal = int(res, 16) / 1e18
                out.append((name, sym, bal))
            except Exception:
                pass
    return out


def check_evm_tokens(address, rpcs):
    tokens = [
        ("USDT", "0xdAC17F958D2ee523a2206206994597C13D831ec7", 6),
        ("USDC", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6),
        ("DAI", "0x6B175474E89094C44Da98b954EedeAC495271d0F", 18),
        ("WETH", "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", 18),
        ("LINK", "0x514910771AF9Ca656af840dff83E8264EcF986CA", 18),
    ]
    out = []
    for name, contract, decimals in tokens:
        data = "0x70a08231" + address[2:].lower().rjust(64, "0")
        st, res = rpc_call(rpcs, "eth_call", [{"to": contract, "data": data}, "latest"])
        if res is not None:
            try:
                val = int(res, 16)
                if val > 0:
                    out.append((name, val / (10 ** decimals)))
            except Exception:
                pass
    return out


# ---------------------------------------------------------------------------
# Chain-spezifische Checks
# ---------------------------------------------------------------------------
def check_bitcoin(address):
    status, text = http_get(f"https://blockchain.info/rawaddr/{address}?limit=0")
    if status == 200:
        try:
            d = json.loads(text)
            return d.get("final_balance", 0) / 1e8, "BTC", d.get("n_tx", 0)
        except Exception:
            pass
    status, text = http_get(f"https://api.blockcypher.com/v1/btc/main/addrs/{address}/balance")
    if status == 200:
        try:
            d = json.loads(text)
            return d.get("balance", 0) / 1e8, "BTC", d.get("n_tx", 0)
        except Exception:
            pass
    return None, None, None


def check_litecoin(address):
    status, text = http_get(f"https://api.blockcypher.com/v1/ltc/main/addrs/{address}/balance")
    if status == 200:
        try:
            d = json.loads(text)
            return d.get("balance", 0) / 1e8, "LTC", d.get("n_tx", 0)
        except Exception:
            pass
    return None, None, None


def check_dogecoin(address):
    status, text = http_get(f"https://api.blockcypher.com/v1/doge/main/addrs/{address}/balance")
    if status == 200:
        try:
            d = json.loads(text)
            return d.get("balance", 0) / 1e8, "DOGE", d.get("n_tx", 0)
        except Exception:
            pass
    return None, None, None


def check_bitcoincash(address):
    addr = address
    if addr.lower().startswith("bitcoincash:"):
        addr = addr.split(":", 1)[1]
    status, text = http_get(f"https://api.blockchair.com/bitcoin-cash/dashboards/address/{addr}")
    if status == 200:
        try:
            d = json.loads(text)
            data = d.get("data", {}).get(addr, {}) or d.get("data", {}).get(address, {})
            bal = data.get("address", {}).get("balance", 0)
            n_tx = data.get("address", {}).get("transaction_count", 0)
            return bal / 1e8, "BCH", n_tx
        except Exception:
            pass
    return None, None, None


def check_solana(address):
    rpcs = ["https://solana-rpc.publicnode.com"]
    st, res = rpc_call(rpcs, "getBalance", [address])
    sol = None
    if res is not None:
        try:
            sol = res.get("value", 0) / 1e9
        except Exception:
            pass
    token_balances = []
    st2, res2 = rpc_call(rpcs, "getTokenAccountsByOwner",
                         [address, {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                          {"encoding": "jsonParsed"}])
    if res2 is not None:
        try:
            for acc in res2.get("value", []):
                info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                amt = info.get("tokenAmount", {}).get("uiAmount")
                mint = info.get("mint")
                if amt and amt > 0:
                    token_balances.append((mint, amt))
        except Exception:
            pass
    return sol, "SOL", token_balances


def check_ripple(address):
    payload = {"method": "account_info", "params": [{"account": address, "ledger_index": "validated"}]}
    st, tx = http_post_json("https://s1.ripple.com:51234", payload)
    if st == 200:
        try:
            d = json.loads(tx)
            result = d.get("result", {})
            if "account_data" in result:
                drops = int(result["account_data"].get("Balance", "0"))
                return drops / 1e6, "XRP", None
        except Exception:
            pass
    return None, None, None


def check_cardano(address):
    status, text = http_get(f"https://api.koios.rest/api/v0/address_info?_address={address}")
    if status == 200:
        try:
            d = json.loads(text)
            if isinstance(d, list) and d:
                info = d[0]
                lovelace = int(info.get("balance", "0"))
                return lovelace / 1e6, "ADA", None
        except Exception:
            pass
    return None, None, None


def check_tron(address):
    status, text = http_get(f"https://api.trongrid.io/v1/accounts/{address}")
    if status == 200:
        try:
            d = json.loads(text)
            data = d.get("data", [])
            if data:
                acc = data[0]
                sun = acc.get("balance", 0)
                trc20 = acc.get("trc20", [])
                token_balances = []
                for t in trc20:
                    for k, v in t.items():
                        try:
                            token_balances.append((k, int(v)))
                        except Exception:
                            pass
                return sun / 1e6, "TRX", token_balances
        except Exception:
            pass
    return None, None, None


def check_cosmos(address):
    # Cosmos Hub REST
    status, text = http_get(f"https://cosmos-rest.publicnode.com/cosmos/bank/v1beta1/balances/{address}")
    if status == 200:
        try:
            d = json.loads(text)
            for b in d.get("balances", []):
                if b.get("denom") == "uatom":
                    return int(b.get("amount", "0")) / 1e6, "ATOM", None
            # fallback first balance
            bals = d.get("balances", [])
            if bals:
                b = bals[0]
                amt = int(b.get("amount", "0"))
                denom = b.get("denom", "")
                # uatom -> ATOM
                if denom.startswith("u"):
                    return amt / 1e6, denom[1:].upper(), None
                return amt, denom, None
        except Exception:
            pass
    return None, None, None


def check_algorand(address):
    status, text = http_get(f"https://mainnet-api.algonode.cloud/v2/accounts/{address}")
    if status == 200:
        try:
            d = json.loads(text)
            micro = d.get("amount", 0)
            return micro / 1e6, "ALGO", None
        except Exception:
            pass
    return None, None, None


def check_stellar(address):
    status, text = http_get(f"https://horizon.stellar.org/accounts/{address}")
    if status == 200:
        try:
            d = json.loads(text)
            for b in d.get("balances", []):
                if b.get("asset_type") == "native":
                    return float(b.get("balance", "0")), "XLM", None
        except Exception:
            pass
    return None, None, None


def check_tezos(address):
    status, text = http_get(f"https://api.tzkt.io/v1/accounts/{address}")
    if status == 200:
        try:
            d = json.loads(text)
            mutez = int(d.get("balance", 0))
            return mutez / 1e6, "XTZ", None
        except Exception:
            pass
    return None, None, None


def check_near(address):
    payload = {"jsonrpc": "2.0", "id": 1, "method": "query",
               "params": {"request_type": "view_account", "finality": "final", "account_id": address}}
    st, tx = http_post_json("https://rpc.mainnet.near.org", payload)
    if st == 200:
        try:
            d = json.loads(tx)
            amt = int(d.get("result", {}).get("amount", "0"))
            return amt / 1e24, "NEAR", None
        except Exception:
            pass
    return None, None, None


def check_aptos(address):
    status, text = http_get(f"https://fullnode.mainnet.aptoslabs.com/v1/accounts/{address}/resource/0x1::coin::CoinStore%3C0x1::aptos_coin::AptosCoin%3E")
    if status == 200:
        try:
            d = json.loads(text)
            val = int(d.get("data", {}).get("coin", {}).get("value", "0"))
            return val / 1e8, "APT", None
        except Exception:
            pass
    return None, None, None


def check_sui(address):
    payload = {"jsonrpc": "2.0", "id": 1, "method": "suix_getBalance",
               "params": [address, "0x2::sui::SUI"]}
    st, tx = http_post_json("https://fullnode.mainnet.sui.io:443", payload)
    if st == 200:
        try:
            d = json.loads(tx)
            total = int(d.get("result", {}).get("totalBalance", "0"))
            return total / 1e9, "SUI", None
        except Exception:
            pass
    return None, None, None


def check_ton(address):
    status, text = http_get(f"https://toncenter.com/api/v2/getAddressBalance?address={address}")
    if status == 200:
        try:
            d = json.loads(text)
            if d.get("ok"):
                nano = int(d.get("result", "0"))
                return nano / 1e9, "TON", None
        except Exception:
            pass
    return None, None, None


# ---------------------------------------------------------------------------
# Adress-Erkennung
# ---------------------------------------------------------------------------
def detect_chain(address):
    a = address.strip()
    # Aptos / Sui (0x + 64 hex) - beide möglich
    if re.fullmatch(r"0x[0-9a-fA-F]{64}", a):
        return "aptos_sui"
    # Ethereum / EVM (0x + 40 hex)
    if re.fullmatch(r"0x[0-9a-fA-F]{40}", a):
        return "evm"
    # Bitcoin bech32
    if re.fullmatch(r"bc1[ac-hj-np-z02-9]{39,59}", a, re.IGNORECASE):
        return "bitcoin"
    if re.fullmatch(r"[13][a-km-zA-HJ-NP-Z1-9]{25,34}", a):
        if len(a) >= 46:
            return "polkadot"
        return "bitcoin"
    # Litecoin
    if re.fullmatch(r"[LM][a-km-zA-HJ-NP-Z1-9]{26,33}", a) or re.fullmatch(r"ltc1[ac-hj-np-z02-9]{39,59}", a, re.IGNORECASE):
        return "litecoin"
    # Dogecoin
    if re.fullmatch(r"D[5-9A-HJ-NP-U][1-9A-HJ-NP-Za-km-z]{32}", a):
        return "dogecoin"
    # Ripple
    if re.fullmatch(r"r[1-9A-HJ-NP-Za-km-z]{24,34}", a):
        return "ripple"
    # Cardano
    if a.startswith("addr1") or a.startswith("addr_test1"):
        return "cardano"
    # Tron
    if re.fullmatch(r"T[1-9A-HJ-NP-Za-km-z]{33}", a):
        return "tron"
    # Bitcoin Cash
    if a.lower().startswith("bitcoincash:") or re.fullmatch(r"[qp][a-z0-9]{41}", a, re.IGNORECASE):
        return "bitcoincash"
    # Cosmos
    if re.fullmatch(r"cosmos1[0-9a-z]{38,}", a):
        return "cosmos"
    # Algorand (58 uppercase base32)
    if re.fullmatch(r"[A-Z2-7]{58}", a):
        return "algorand"
    # Stellar
    if re.fullmatch(r"G[ABCDEFGHIJKLMNOPQRSTUVWXYZ234567]{55}", a):
        return "stellar"
    # Tezos
    if re.fullmatch(r"tz[123][a-zA-Z0-9]{33}", a) or re.fullmatch(r"KT1[a-zA-Z0-9]{33}", a):
        return "tezos"
    # NEAR
    if a.endswith(".near") or re.fullmatch(r"[0-9a-f]{64}", a):
        return "near"
    # TON
    if re.fullmatch(r"(EQ|UQ|kQ)[A-Za-z0-9_-]{46}", a):
        return "ton"
    # Solana (base58)
    if re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", a):
        return "solana"
    return None


CHAIN_NAMES = {
    "evm": "EVM (Multi-Chain)",
    "aptos_sui": "Aptos / Sui",
    "bitcoin": "Bitcoin (BTC)",
    "ethereum": "Ethereum (ETH)",
    "litecoin": "Litecoin (LTC)",
    "dogecoin": "Dogecoin (DOGE)",
    "solana": "Solana (SOL)",
    "ripple": "Ripple (XRP)",
    "cardano": "Cardano (ADA)",
    "tron": "Tron (TRX)",
    "bitcoincash": "Bitcoin Cash (BCH)",
    "polkadot": "Polkadot (DOT)",
    "cosmos": "Cosmos (ATOM)",
    "algorand": "Algorand (ALGO)",
    "stellar": "Stellar (XLM)",
    "tezos": "Tezos (XTZ)",
    "near": "NEAR",
    "ton": "TON",
}


def fmt(num):
    if num is None:
        return "n/a"
    if isinstance(num, float):
        if num == 0:
            return "0"
        if abs(num) < 0.0001:
            return f"{num:.8f}"
        return f"{num:,.8f}".rstrip("0").rstrip(".")
    return str(num)


# ---------------------------------------------------------------------------
# Verarbeitung
# ---------------------------------------------------------------------------
def process_address(address):
    address = address.strip()
    res = {"address": address, "chain": None, "results": [], "tokens": None, "error": None}
    if not address:
        res["error"] = "leer"
        return res
    chain = detect_chain(address)
    res["chain"] = CHAIN_NAMES.get(chain, "Nicht erkannt") if chain else "Nicht erkannt"
    if chain is None:
        res["error"] = "Chain nicht erkannt"
        return res

    try:
        if chain == "evm":
            res["results"] = check_evm_address(address)
            # tokens only on Ethereum mainnet RPCs
            eth_rpcs = ["https://cloudflare-eth.com", "https://ethereum-rpc.publicnode.com"]
            toks = check_evm_tokens(address, eth_rpcs)
            if toks:
                res["tokens"] = ("Ethereum", toks)
        elif chain == "aptos_sui":
            # try both
            r1 = check_aptos(address)
            r2 = check_sui(address)
            if r1[0] is not None:
                res["results"].append(("Aptos", "APT", r1[0]))
            if r2[0] is not None:
                res["results"].append(("Sui", "SUI", r2[0]))
            if not res["results"]:
                # show attempt
                res["results"].append(("Aptos", "APT", None))
        elif chain == "bitcoin":
            bal, sym, ntx = check_bitcoin(address)
            res["results"].append(("Bitcoin", sym, bal))
            res["txs"] = ntx
        elif chain == "litecoin":
            bal, sym, ntx = check_litecoin(address)
            res["results"].append(("Litecoin", sym, bal))
            res["txs"] = ntx
        elif chain == "dogecoin":
            bal, sym, ntx = check_dogecoin(address)
            res["results"].append(("Dogecoin", sym, bal))
            res["txs"] = ntx
        elif chain == "bitcoincash":
            bal, sym, ntx = check_bitcoincash(address)
            res["results"].append(("Bitcoin Cash", sym, bal))
            res["txs"] = ntx
        elif chain == "solana":
            bal, sym, toks = check_solana(address)
            res["results"].append(("Solana", sym, bal))
            if toks:
                res["tokens"] = ("Solana", toks)
        elif chain == "ripple":
            bal, sym, _ = check_ripple(address)
            res["results"].append(("Ripple", sym, bal))
        elif chain == "cardano":
            bal, sym, _ = check_cardano(address)
            res["results"].append(("Cardano", sym, bal))
        elif chain == "tron":
            bal, sym, toks = check_tron(address)
            res["results"].append(("Tron", sym, bal))
            if toks:
                res["tokens"] = ("Tron", toks)
        elif chain == "cosmos":
            bal, sym, _ = check_cosmos(address)
            res["results"].append(("Cosmos", sym, bal))
        elif chain == "algorand":
            bal, sym, _ = check_algorand(address)
            res["results"].append(("Algorand", sym, bal))
        elif chain == "stellar":
            bal, sym, _ = check_stellar(address)
            res["results"].append(("Stellar", sym, bal))
        elif chain == "tezos":
            bal, sym, _ = check_tezos(address)
            res["results"].append(("Tezos", sym, bal))
        elif chain == "near":
            bal, sym, _ = check_near(address)
            res["results"].append(("NEAR", sym, bal))
        elif chain == "ton":
            bal, sym, _ = check_ton(address)
            res["results"].append(("TON", sym, bal))
        elif chain == "polkadot":
            res["error"] = "Polkadot-Balance-Abfrage nicht implementiert (komplexe RPC)"
        else:
            res["error"] = "Keine Abfrage implementiert"
    except Exception as e:
        res["error"] = str(e)
    return res


def print_result(res):
    print("=" * 60)
    print(f"Adresse : {res['address']}")
    print(f"Chain   : {res['chain']}")
    if res.get("error"):
        print(f"Fehler  : {res['error']}")
    for name, sym, bal in res.get("results", []):
        if bal is None:
            continue
        # nur anzeigen wenn >0 oder EVM multi-chain: zeige alle mit Guthaben, sonst nur 0? Zeige alle EVM
        print(f"  {name:22s}: {fmt(bal)} {sym}")
    # EVM: falls alle 0, zeige Hinweis
    if res["chain"] == "EVM (Multi-Chain)":
        nonzero = [r for r in res["results"] if r[2] and r[2] > 0]
        if not nonzero:
            print("  (Kein Guthaben auf den geprüften EVM-Chains)")
    tokens = res.get("tokens")
    if tokens:
        chainname, toks = tokens
        print(f"Token-Guthaben ({chainname}):")
        for t in toks:
            if isinstance(t, tuple) and len(t) == 2:
                print(f"   - {fmt(t[1])} {t[0]}")
    if res.get("txs") is not None:
        print(f"Transaktionen: {res['txs']}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Prüft Krypto-Wallet-Adressen auf Guthaben und Währung.")
    parser.add_argument("address", nargs="?", help="Eine einzelne Wallet-Adresse")
    parser.add_argument("-f", "--file", help="Textdatei mit mehreren Adressen (eine pro Zeile)")
    parser.add_argument("--human", action="store_true", help="Zufällige Wartezeiten zwischen Abfragen")
    parser.add_argument("--min-delay", type=float, default=1.0, help="Min. Wartezeit in Sekunden (Default: 1.0)")
    parser.add_argument("--max-delay", type=float, default=5.0, help="Max. Wartezeit in Sekunden (Default: 5.0)")
    parser.add_argument("-o", "--output", help="Ergebnisse in diese Datei schreiben")
    args = parser.parse_args()

    addresses = []
    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    addresses.append(line)
        except FileNotFoundError:
            print(f"Datei nicht gefunden: {args.file}")
            sys.exit(1)
    if args.address:
        addresses.append(args.address.strip())

    if not addresses:
        try:
            inp = input("Wallet-Adresse (oder Pfad zu .txt): ").strip()
        except EOFError:
            print("Keine Adresse angegeben.")
            sys.exit(1)
        if inp.lower().endswith(".txt"):
            try:
                with open(inp, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            addresses.append(line)
            except FileNotFoundError:
                print(f"Datei nicht gefunden: {inp}")
                sys.exit(1)
        else:
            addresses.append(inp)

    if not addresses:
        print("Keine Adressen zu prüfen.")
        sys.exit(1)

    out_lines = []
    total = len(addresses)
    for i, addr in enumerate(addresses, 1):
        print(f"\n[{i}/{total}] Prüfe: {addr}")
        res = process_address(addr)
        print_result(res)
        rec = f"{res['address']} | {res['chain']}"
        for name, sym, bal in res.get("results", []):
            if bal is not None and bal > 0:
                rec += f" | {fmt(bal)} {sym} ({name})"
        if res.get("tokens"):
            cn, toks = res["tokens"]
            rec += " | Tokens: " + ", ".join(f"{fmt(t[1])} {t[0]}" for t in toks)
        if res.get("error"):
            rec += f" | Fehler: {res['error']}"
        out_lines.append(rec)

        if args.human and i < total:
            delay = random.uniform(args.min_delay, args.max_delay)
            print(f"  ... warte {delay:.2f}s (Human-Modus)")
            time.sleep(delay)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write("\n".join(out_lines) + "\n")
        print(f"\nErgebnisse gespeichert in: {args.output}")

    print("\nHinweis: Guthaben von 0 bedeutet: Adresse bekannt, aber leer.")


if __name__ == "__main__":
    main()
