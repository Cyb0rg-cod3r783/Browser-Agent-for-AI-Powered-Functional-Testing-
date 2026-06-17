from qdrant_client import QdrantClient, models

class VectorDB:
    def __init__(self, host="localhost", port=6333):
        """
        Initializes the Qdrant client.
        """
        self.client = QdrantClient(host=host, port=port)

    def create_collections(self):
        """
        Creates the 'pages' and 'elements' collections in Qdrant if they
        don't already exist. These collections will store the vector
        embeddings for our pages and elements.
        """
        # The vector size needs to match the output dimension of the
        # sentence-transformer model we'll be using. A common size is 384.
        vector_size = 384

        existing = {c.name for c in self.client.get_collections().collections}

        # Create the 'pages' collection if it doesn't exist
        if "pages" not in existing:
            self.client.create_collection(
                collection_name="pages",
                vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
            )

        # Create the 'elements' collection if it doesn't exist
        if "elements" not in existing:
            self.client.create_collection(
                collection_name="elements",
                vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
            )

    def add_vectors(self, collection_name: str, vectors: list, payloads: list):
        """
        Adds vectors and their associated payloads to a specified collection.
        """
        self.client.upsert(
            collection_name=collection_name,
            points=models.Batch(
                ids=[i for i in range(len(vectors))], # Simple sequential IDs for now
                vectors=vectors,
                payloads=payloads
            ),
            wait=True
        )

    def search(self, collection_name: str, vector: list, limit: int = 1):
        """
        Searches a collection for the most similar vectors.
        """
        search_result = self.client.search(
            collection_name=collection_name,
            query_vector=vector,
            limit=limit,
        )
        return search_result

# Initialize a single instance of the VectorDB to be used across the application
vector_db_client = VectorDB()