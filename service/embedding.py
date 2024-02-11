import asyncio
import copy
from tempfile import NamedTemporaryFile
from typing import Any, List, Optional, Union

import numpy as np
import requests
from llama_index import Document, SimpleDirectoryReader
from llama_index.node_parser import SimpleNodeParser
from tqdm import tqdm

from encoders import BaseEncoder
import encoders
from models.file import File
from models.ingest import EncoderEnum
from service.vector_database import get_vector_service
from utils.summarise import completion


class EmbeddingService:
    def __init__(self, files: List[File], index_name: str, vector_credentials: dict):
        self.files = files
        self.index_name = index_name
        self.vector_credentials = vector_credentials

    def _get_datasource_suffix(self, type: str) -> str:
        suffixes = {
            "TXT": ".txt",
            "PDF": ".pdf",
            "MARKDOWN": ".md",
            "DOCX": ".docx",
        }
        try:
            return suffixes[type]
        except KeyError:
            raise ValueError("Unsupported datasource type")

    async def generate_documents(self) -> List[Document]:
        documents = []
        for file in tqdm(self.files, desc="Generating documents"):
            suffix = self._get_datasource_suffix(file.type.value)
            with NamedTemporaryFile(suffix=suffix, delete=True) as temp_file:
                with requests.get(url=file.url) as response:  # Add context manager here
                    temp_file.write(response.content)
                    temp_file.flush()
                reader = SimpleDirectoryReader(input_files=[temp_file.name])
                docs = reader.load_data()
                for doc in docs:
                    doc.metadata["file_url"] = file.url
                documents.extend(docs)
        return documents

    async def generate_chunks(
        self, documents: List[Document]
    ) -> List[Union[Document, None]]:
        parser = SimpleNodeParser.from_defaults(chunk_size=350, chunk_overlap=20)
        nodes = parser.get_nodes_from_documents(documents, show_progress=False)
        return nodes

    async def generate_embeddings(
        self,
        nodes: List[Union[Document, None]],
        encoder: BaseEncoder,
        index_name: Optional[str] = None,
    ) -> List[tuple[str, list, dict[str, Any]]]:
        pbar = tqdm(total=len(nodes), desc="Generating embeddings")

        async def generate_embedding(node):
            if node is not None:
                embeddings: List[np.ndarray] = [
                    np.array(e) for e in encoder([node.text])
                ]
                embedding = (
                    node.id_,
                    embeddings[0].tolist(),
                    {
                        **node.metadata,
                        "content": node.text,
                    },
                )
                pbar.update()
                return embedding

        tasks = [generate_embedding(node) for node in nodes]
        embeddings = await asyncio.gather(*tasks)
        pbar.close()
        vector_service = get_vector_service(
            index_name=index_name or self.index_name,
            credentials=self.vector_credentials,
            encoder=encoder,
        )
        await vector_service.upsert(embeddings=[e for e in embeddings if e is not None])

        return [e for e in embeddings if e is not None]

    async def generate_summary_documents(
        self, documents: List[Document]
    ) -> List[Document]:
        pbar = tqdm(total=len(documents), desc="Summarizing documents")
        summary_documents = []
        for document in documents:
            doc_copy = copy.deepcopy(document)  # Make a copy of the document
            doc_copy.text = await completion(document=doc_copy)
            summary_documents.append(doc_copy)
            pbar.update()
        pbar.close()
        return summary_documents


def get_encoder(*, encoder_type: EncoderEnum) -> encoders.BaseEncoder:
    encoder_mapping = {
        EncoderEnum.cohere: encoders.CohereEncoder,
        EncoderEnum.openai: encoders.OpenAIEncoder,
        EncoderEnum.huggingface: encoders.HuggingFaceEncoder,
        EncoderEnum.fastembed: encoders.FastEmbedEncoder,
    }

    encoder_class = encoder_mapping.get(encoder_type)
    if encoder_class is None:
        raise ValueError(f"Unsupported encoder: {encoder_type}")
    return encoder_class()
