# Setting up llama.cpp server with Caddy Reverse Proxy

## Instructions
1. Compile latest [llama.cpp](https://github.com/ggml-org/llama.cpp)
2. Prepare local language model from [unsloth](https://huggingface.co/unsloth)
3. Serve local language model
4. Configure [Caddy](https://github.com/caddyserver/caddy) Reverse Proxy

## Compile Latest llama.cpp

### CUDA Example
```shell
git clone https://github.com/ggml-org/llama.cpp.git
cd llama.cpp
cmake -B build -DGGML_CUDA=ON
cmake --build build --config Release
```

## Prepare Local Language Model from Unsloth

### Gemma 4 - E4B example
```shell
export HF_TOKEN=
export MODEL_NAME=gemma-4-E4B-it
export QUANT_TYPE=Q4_K_M
export MODELS_DIR=~/models/llm/$MODEL_NAME
mkdir -p $MODELS_DIR
# Download transformer
curl -L https://huggingface.co/unsloth/$MODEL_NAME-GGUF/tree/main/$MODEL_NAME-$QUANT_TYPE.gguf \
    -o $MODELS_DIR/$MODEL_NAME/$MODEL_NAME-$QUANT_TYPE.gguf \
    -H "Authorization: Bearer $HF_TOKEN"
# Download encoder
curl -L https://huggingface.co/unsloth/$MODEL_NAME-GGUF/tree/main/mmproj-BF16.gguf \
    -o $MODELS_DIR/$MODEL_NAME/mmproj-BF16.gguf \
    -H "Authorization: Bearer $HF_TOKEN"
```

## Serve Local Language Model

```shell
API_KEY=$(openssl rand -hex 32)
echo "API_KEY: $API_KEY"

llama.cpp/build/bin/llama-server \
--models-dir ~/models/llm \
--host 0.0.0.0 \
--port 8080 \
--fit on\
--cache-type-k q4_0 \
--cache-type-v q4_0 \
--flash-attn on \
--api-key "$API_KEY" \
```

## Configure Caddy Reverse Proxy

### Install Caddy
```shell
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
```

### Prepare Caddyfile

```caddyfile
# Replace 192.168.1.50 with your server's actual LAN IP
192.168.1.50 {
    # This tells Caddy to use its internal CA instead of Let's Encrypt
    tls internal

    # Forward all traffic to the local llama.cpp instance
    reverse_proxy 127.0.0.1:8080

    # Optional: Enable the PKI endpoint so you can download the
    # root certificate directly from a browser on your client
    handle_path /pki* {
        file_server browse
    }
}
```

### Manual Run

```shell
sudo caddy run --config /path/to/Caddyfile
```

crt path: `/root/.local/share/caddy/pki/authorities/local/root.crt`

```
sudo cp /root/.local/share/caddy/pki/authorities/local/root.crt ~/llama_root.crt
sudo chown $USER:$USER ~/llama_root.crt
```
