package org.jjikmuk.backend.domain.user

import jakarta.persistence.*
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.http.*
import org.springframework.security.core.Authentication
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import org.springframework.web.bind.annotation.*
import org.springframework.web.multipart.MultipartFile
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.time.Instant
import javax.imageio.ImageIO

/** Small private avatars live in the shared DB, not a public product-image bucket. */
@Entity @Table(name = "profile_photos")
class ProfilePhoto(@Id val userId: Long,
    @Lob @Column(nullable = false, columnDefinition = "LONGBLOB") var content: ByteArray,
    @Column(nullable = false, length = 32) var contentType: String,
    @Column(nullable = false) var updatedAt: Instant = Instant.now())
interface ProfilePhotoRepository : JpaRepository<ProfilePhoto, Long>

@Service
class ProfilePhotoService(private val photos: ProfilePhotoRepository, private val users: UserRepository) {
    @Transactional(readOnly = true)
    fun get(owner: Long): ProfilePhoto = photos.findById(owner).orElseThrow {
        CustomException(HttpStatus.NOT_FOUND, "등록된 프로필 사진이 없습니다.", "PHOTO_NOT_FOUND")
    }

    @Transactional
    fun upload(owner: Long, file: MultipartFile): Map<String, Any> {
        if (file.isEmpty || file.size > MAX_BYTES) throw CustomException(HttpStatus.PAYLOAD_TOO_LARGE,
            "사진은 비어 있지 않은 2MiB 이하 파일이어야 합니다.", "PHOTO_TOO_LARGE", "file")
        if (file.contentType !in setOf("image/jpeg", "image/png")) throw invalid()
        val encoded = try {
            ImageIO.createImageInputStream(ByteArrayInputStream(file.bytes)).use { stream ->
                val reader = ImageIO.getImageReaders(stream).asSequence().firstOrNull() ?: throw invalid()
                try {
                    reader.input = stream
                    val format = reader.formatName.lowercase()
                    if (format !in setOf("jpeg", "jpg", "png")) throw invalid()
                    val actualType = if (format == "png") "image/png" else "image/jpeg"
                    if (actualType != file.contentType || reader.getWidth(0) !in 1..4096 || reader.getHeight(0) !in 1..4096) throw invalid()
                    val image = reader.read(0)
                    val output = ByteArrayOutputStream()
                    // Re-encode pixels only: strips EXIF/GPS and trailing payloads.
                    if (!ImageIO.write(image, if (format == "png") "png" else "jpeg", output)) throw invalid()
                    if (output.size() > MAX_BYTES) throw CustomException(HttpStatus.PAYLOAD_TOO_LARGE, "변환한 사진이 2MiB를 초과합니다.", "PHOTO_TOO_LARGE")
                    output.toByteArray() to actualType
                } finally { reader.dispose() }
            }
        } catch (e: CustomException) { throw e } catch (_: Exception) { throw invalid() }
        val user = users.lockById(owner) ?: throw CustomException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다.", "USER_NOT_FOUND")
        val photo = photos.findById(owner).orElse(null)
        if (photo == null) photos.save(ProfilePhoto(owner, encoded.first, encoded.second))
        else { photo.content = encoded.first; photo.contentType = encoded.second; photo.updatedAt = Instant.now() }
        user.hasProfilePhoto = true
        return mapOf("photoUrl" to "/api/users/me/photo", "authenticationRequired" to true)
    }

    @Transactional
    fun delete(owner: Long) {
        val user = users.lockById(owner) ?: throw CustomException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다.", "USER_NOT_FOUND")
        photos.deleteById(owner)
        user.hasProfilePhoto = false
    }
    private fun invalid() = CustomException(HttpStatus.BAD_REQUEST, "실제 JPEG/PNG 사진만 지원하며 최대 4096×4096 픽셀입니다.", "PHOTO_INVALID", "file")
    private companion object { const val MAX_BYTES = 2 * 1024 * 1024 }
}

@RestController @RequestMapping("/api/users/me/photo")
class ProfilePhotoController(private val service: ProfilePhotoService) {
    @GetMapping fun get(auth: Authentication): ResponseEntity<ByteArray> {
        val photo = service.get(auth.principal.toString().toLong())
        return ResponseEntity.ok().contentType(MediaType.parseMediaType(photo.contentType))
            .cacheControl(CacheControl.noStore()).header("X-Content-Type-Options", "nosniff").body(photo.content)
    }
    @PutMapping(consumes = [MediaType.MULTIPART_FORM_DATA_VALUE])
    fun upload(@RequestParam("file") file: MultipartFile, auth: Authentication) =
        mapOf("message" to "프로필 사진 저장 성공", "data" to service.upload(auth.principal.toString().toLong(), file))
    @DeleteMapping fun delete(auth: Authentication): Map<String, String> {
        service.delete(auth.principal.toString().toLong())
        return mapOf("message" to "기본 프로필 이미지로 초기화했습니다.")
    }
}
