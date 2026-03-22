package com.asyncaiflow.controller;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import com.asyncaiflow.support.ApiException;
import com.asyncaiflow.web.Result;
import com.asyncaiflow.web.dto.FileUploadResponse;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;

@RestController
@RequestMapping({"/api/files", "/api/v1/files"})
@Tag(name = "File Upload", description = "Minimal upload API for raw 3D scan files")
public class FileUploadController {

    private static final Logger LOGGER = LoggerFactory.getLogger(FileUploadController.class);

    private static final Set<String> ALLOWED_EXTENSIONS = Set.of("obj", "ply");
    private static final DateTimeFormatter FILE_TS_FORMAT = DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss");

    private final Path uploadDir;

    public FileUploadController(@Value("${asyncaiflow.upload-dir:/tmp/asyncaiflow_uploads}") String uploadDir) {
        this.uploadDir = Path.of(uploadDir).toAbsolutePath().normalize();
    }

    @PostMapping(value = "/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    @Operation(summary = "Upload a raw scan file", description = "Accepts .obj/.ply scan files and returns local path for rawScanUrl")
    public Result<FileUploadResponse> upload(@RequestParam("file") MultipartFile file) {
        if (file == null || file.isEmpty()) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "INVALID_ARGUMENT", "upload file must not be empty");
        }

        String incomingFileName = file.getOriginalFilename();
        String originalFileName;
        if (incomingFileName == null || incomingFileName.isBlank()) {
            originalFileName = "scan";
        } else {
            originalFileName = incomingFileName.trim();
        }
        String extension = resolveExtension(originalFileName);
        if (!ALLOWED_EXTENSIONS.contains(extension.toLowerCase(Locale.ROOT))) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "INVALID_ARGUMENT", "only .obj and .ply files are supported");
        }

        try {
            Files.createDirectories(uploadDir);
            String saveName = FILE_TS_FORMAT.format(LocalDateTime.now())
                    + "_"
                    + UUID.randomUUID().toString().replace("-", "")
                    + "."
                    + extension;
            Path target = uploadDir.resolve(saveName).normalize();
            if (!target.startsWith(uploadDir)) {
                throw new ApiException(HttpStatus.BAD_REQUEST, "INVALID_ARGUMENT", "invalid upload path");
            }
            Files.createDirectories(target.getParent());

            try (InputStream input = file.getInputStream()) {
                Files.copy(input, target, StandardCopyOption.REPLACE_EXISTING);
            }

            return Result.ok("file uploaded", new FileUploadResponse(
                    originalFileName,
                    target.toString(),
                    file.getSize()
            ));
        } catch (IOException exception) {
            LOGGER.error("Failed to save upload file to {}", uploadDir, exception);
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "failed to save upload file");
        }
    }

    private String resolveExtension(String fileName) {
        int index = fileName.lastIndexOf('.');
        if (index < 0 || index == fileName.length() - 1) {
            return "";
        }
        return fileName.substring(index + 1);
    }
}
