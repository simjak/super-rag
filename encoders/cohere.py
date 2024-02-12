from typing import List, Optional

import cohere
from decouple import config

from encoders import BaseEncoder


class CohereEncoder(BaseEncoder):
    client: Optional[cohere.Client] = None
    type: str = "cohere"
    dimension: int = 1024  # https://docs.cohere.com/reference/embed

    def __init__(
        self,
        name: Optional[str] = None,
        cohere_api_key: Optional[str] = None,
        score_threshold: float = 0.3,
    ):
        if name is None:
            name = config("COHERE_MODEL_NAME", "embed-english-v3.0")
        super().__init__(name=name, score_threshold=score_threshold)
        cohere_api_key = cohere_api_key or config("COHERE_API_KEY")
        if cohere_api_key is None:
            raise ValueError("Cohere API key cannot be 'None'.")
        try:
            self.client = cohere.Client(cohere_api_key)
        except Exception as e:
            raise ValueError(
                f"Cohere API client failed to initialize. Error: {e}"
            ) from e

    def __call__(self, docs: List[str]) -> List[List[float]]:
        if self.client is None:
            raise ValueError("Cohere client is not initialized.")
        try:
            embeds = self.client.embed(docs, input_type="search_query", model=self.name)
            return embeds.embeddings
        except Exception as e:
            raise ValueError(f"Cohere API call failed. Error: {e}") from e
