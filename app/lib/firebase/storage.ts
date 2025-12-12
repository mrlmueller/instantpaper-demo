import { getStorage, ref, uploadBytes, getDownloadURL, deleteObject } from 'firebase/storage';
import { firebaseApp } from './config';
import type { ImageMetadata } from '@/app/actions/quellen';

/**
 * Upload images to Firebase Storage from the client
 * Returns metadata for each uploaded image
 */
export async function uploadImagesToStorage(
  userId: string,
  imageFiles: File[]
): Promise<ImageMetadata[]> {
  const storage = getStorage(firebaseApp);
  const tempId = `temp_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`;

  const uploadPromises = imageFiles.map(async (file, index) => {
    const timestamp = Date.now();
    const sanitized = file.name.replace(/[^a-zA-Z0-9._-]/g, '_');
    const path = `users/${userId}/quellen/${tempId}/${timestamp}_${index}_${sanitized}`;

    const storageRef = ref(storage, path);
    await uploadBytes(storageRef, file, { contentType: file.type });
    const url = await getDownloadURL(storageRef);

    return {
      url,
      path,
      filename: file.name,
      size: file.size,
      contentType: file.type,
    };
  });

  return await Promise.all(uploadPromises);
}

/**
 * Delete images from Firebase Storage
 * Used for cleanup when Quelle creation fails
 */
export async function deleteImagesFromStorage(imagePaths: string[]): Promise<void> {
  const storage = getStorage(firebaseApp);

  const deletePromises = imagePaths.map(async (path) => {
    try {
      const storageRef = ref(storage, path);
      await deleteObject(storageRef);
    } catch (error: any) {
      if (error.code !== 'storage/object-not-found') {
        console.error(`Failed to delete image ${path}:`, error);
      }
    }
  });

  await Promise.all(deletePromises);
}
