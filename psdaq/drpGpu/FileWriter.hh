/**
 * @file
 * @brief Drp::Gpu::FileWriter and FileWriterAsync, which write event data held in GPU memory to files with NVIDIA cuFile.
 */
#pragma once

#include <cstddef>                      // size_t
#include <cstdint>                      // uint*_t
#include <string>

#include <cuda_runtime.h>
#include "cufile.h"                     // CUfileHandle_t

#include "drp/FileWriterBase.hh"

namespace Drp {
  namespace Gpu {

/** Writes event data that is already in GPU memory to a file with NVIDIA cuFile. Events are copied device to device into a GPU buffer, which is written to the file when the next event would not fit or the oldest buffered event is more than 2 seconds older than the new one. */
class FileWriter : public Drp::FileWriterBase
{
public:
  /** Open the cuFile driver and allocate a GPU buffer of bufferSize bytes, reduced to the driver's maximum pinned memory size if larger. Exits if bufferSize is not a power of 2 or the driver cannot be opened; dio adds O_DIRECT when open() creates a file. */
  FileWriter(size_t bufferSize, bool dio);
  /** Close the file, free the GPU buffer and close the cuFile driver, exiting if that fails. */
  ~FileWriter() override;
  /** Log the cuFile driver properties: versions, supported file systems, control and feature flags and size limits. */
  static void dumpProperties();
  /** Use stream for the buffer copies and register it with cuFile (flags 0x7). Returns -1 on failure, else 0. */
  int registerStream(cudaStream_t);
  /** Deregister the stream set by registerStream(), if any, and forget it; the argument is not used. Returns -1 on failure, else 0. */
  int deregisterStream(cudaStream_t);
  int open(const std::string& fileName) override;
  int close() override;
  void writeEvent(const void* devPtr, size_t size, const XtcData::TimeStamp) override;
private:
  virtual void _reset();
  virtual void _flush();
  ssize_t _write();
protected:
  cudaStream_t       m_stream;
  CUfileHandle_t     m_handle;
  XtcData::TimeStamp m_batch_starttime;
  uint8_t*           m_buffer_d;        // device pointer
  off_t              m_fileOffset;
  size_t             m_bufferSize;
  int                m_fd;
  bool               m_dio;
private:
  size_t             m_count;
};

/** FileWriter that splits its GPU buffer into two halves: a filled half is written with cuFileWriteAsync on the registered stream while events are copied into the other half. */
class FileWriterAsync : public FileWriter
{
public:
  /** Allocate a GPU buffer of twice bufferSize, used as two halves of bufferSize bytes. */
  FileWriterAsync(size_t bufferSize, bool dio);
  void writeEvent(const void* devPtr, size_t size, const XtcData::TimeStamp) override;
protected:
  void _reset() override;
  void _flush() override;
private:
  void _write();
private:
  size_t   m_counts[2];
  off_t    m_bufOffset[2];
  size_t   m_index;
  ssize_t  m_bytesWritten;
};

  } // Gpu
} // Drp
