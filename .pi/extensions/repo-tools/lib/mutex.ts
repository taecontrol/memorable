let repoMutationQueue: Promise<void> = Promise.resolve();

export async function withRepoMutationLock<T>(operation: () => Promise<T>): Promise<T> {
	const previous = repoMutationQueue;
	let release!: () => void;
	repoMutationQueue = new Promise<void>((resolve) => {
		release = resolve;
	});

	await previous;
	try {
		return await operation();
	} finally {
		release();
	}
}
