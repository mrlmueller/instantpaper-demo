import { getStorage, ref, uploadBytes, getDownloadURL, deleteObject, getBlob } from 'firebase/storage';
import { firebaseApp } from './config';
import type { ImageMetadata } from '@/app/actions/quellen';

async function readImageDimensions(file: File): Promise<{ widthPx: number; heightPx: number } | null> {
  try {
    const bitmap = await createImageBitmap(file);
    try {
      return { widthPx: bitmap.width, heightPx: bitmap.height };
    } finally {
      bitmap.close();
    }
  } catch {
    // ignore
  }

  let objectUrl: string | null = null;
  try {
    objectUrl = URL.createObjectURL(file);
    const img = new Image();
    img.decoding = 'async';
    img.src = objectUrl;

    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error('Failed to load image for dimension probing'));
    });

    const widthPx = img.naturalWidth || img.width;
    const heightPx = img.naturalHeight || img.height;
    if (widthPx > 0 && heightPx > 0) return { widthPx, heightPx };
  } catch {
    // ignore
  } finally {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  }

  return null;
}

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

    const dims = await readImageDimensions(file);

    const storageRef = ref(storage, path);
    await uploadBytes(storageRef, file, { contentType: file.type });
    const url = await getDownloadURL(storageRef);

    return {
      url,
      path,
      filename: file.name,
      size: file.size,
      contentType: file.type,
      ...(dims ?? {}),
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

export async function getDownloadUrlFromStorage(path: string): Promise<string> {
  const storage = getStorage(firebaseApp);
  const storageRef = ref(storage, path);
  return getDownloadURL(storageRef);
}

export async function downloadFileFromStorage(path: string, filename: string): Promise<void> {
  const storage = getStorage(firebaseApp);
  const storageRef = ref(storage, path);

  // Prefer authenticated blob downloads to avoid opening a new tab and to respect Storage rules.
  const blob = await getBlob(storageRef);
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename || 'download';
    a.rel = 'noreferrer';
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }
}
