"""Provider-specific input encoding and response normalization."""
import base64
import os
from dataclasses import dataclass


@dataclass
class Reply:
    text: str
    usage: dict
    model: str


def credential(name):
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"Missing environment variable {name}")
    return value


def generate(config, system, prompt, files=()):
    provider = config["provider"]
    if provider == "mock":
        evidence = any(path.suffix.lower() != ".pdf" and
                       "security@example.invalid" in path.read_text(encoding="utf-8")
                       for path in files) or "security@example.invalid" in prompt
        return Reply("Report to security@example.invalid." if evidence else
                     "I do not have the policy.", {}, "fixture")
    model = config["id"]
    limit = config.get("max_tokens", 1024)
    if provider == "openai":
        from openai import OpenAI

        content = [{"type": "input_text", "text": prompt}]
        for path in files:
            mime = "application/pdf" if path.suffix.lower() == ".pdf" else "text/plain"
            data = base64.b64encode(path.read_bytes()).decode("ascii")
            content.append({"type": "input_file", "filename": path.name,
                            "file_data": f"data:{mime};base64,{data}"})
        with OpenAI(api_key=credential("OPENAI_API_KEY"), timeout=60, max_retries=0) as client:
            result = client.responses.create(
                model=model, instructions=system, store=False, max_output_tokens=limit,
                input=[{"role": "user", "content": content}],
            )
        if result.status != "completed" or not result.output_text.strip():
            raise ValueError("OpenAI response did not contain a complete answer")
        return Reply(result.output_text, result.usage.model_dump() if result.usage else {},
                     result.model)
    if provider == "anthropic":
        from anthropic import Anthropic

        content = [{"type": "text", "text": prompt}]
        for path in files:
            if path.suffix.lower() == ".pdf":
                data = base64.b64encode(path.read_bytes()).decode("ascii")
                content.append({"type": "document", "source": {
                    "type": "base64", "media_type": "application/pdf", "data": data}})
            else:
                content.append({"type": "text", "text":
                                f"Reference file {path.name}:\n{path.read_text(encoding='utf-8')}"})
        with Anthropic(api_key=credential("ANTHROPIC_API_KEY"),
                       timeout=60, max_retries=0) as client:
            result = client.messages.create(
                model=model, system=system, max_tokens=limit,
                messages=[{"role": "user", "content": content}],
            )
        answer = "\n".join(block.text for block in result.content if block.type == "text")
        if result.stop_reason != "end_turn" or not answer.strip():
            raise ValueError("Claude response did not contain a complete answer")
        return Reply(answer, result.usage.model_dump(), result.model)
    raise ValueError(f"Unknown model provider: {provider}")
